#include <iostream>
#include <string>
#include <vector>
#include <set>
#include <queue>
#include <unordered_map>
#include <regex>
#include <chrono>
#include <algorithm>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <httplib.h>
#include <jwt-cpp/jwt.h>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

const std::string SHARED_SECRET = "super-secure-shared-secret-key-12345";
const std::string PYTHON_HOST = "127.0.0.1";
const int PYTHON_PORT = 8000;

// --- Thread-Safe Queue for Streaming Bridge ---
class SafeQueue {
private:
    std::queue<std::string> q;
    std::mutex m;
    std::condition_variable cv;
    bool finished = false;

public:
    void push(const std::string& val) {
        std::lock_guard<std::mutex> lock(m);
        q.push(val);
        cv.notify_one();
    }

    void finish() {
        std::lock_guard<std::mutex> lock(m);
        finished = true;
        cv.notify_one();
    }

    bool pop(std::string& val) {
        std::unique_lock<std::mutex> lock(m);
        cv.wait(lock, [this]() { return !q.empty() || finished; });
        if (q.empty() && finished) {
            return false;
        }
        val = q.front();
        q.pop();
        return true;
    }
};

// --- Aho-Corasick Trie Implementation (Case-Insensitive) ---
class AhoCorasick {
public:
    struct Node {
        std::unordered_map<char, Node*> children;
        Node* fail = nullptr;
        size_t match_len = 0; // 0 means no match at this node
    };

    Node* root;
    size_t max_pattern_len = 0;

    AhoCorasick() {
        root = new Node();
    }

    void insert(const std::string& word) {
        Node* curr = root;
        // Normalize to lowercase so all matching is case-insensitive
        for (char c : word) {
            char lc = (char)std::tolower((unsigned char)c);
            if (curr->children.find(lc) == curr->children.end()) {
                curr->children[lc] = new Node();
            }
            curr = curr->children[lc];
        }
        curr->match_len = word.size();
        if (word.size() > max_pattern_len) max_pattern_len = word.size();
    }

    void build() {
        std::queue<Node*> q;
        for (auto& pair : root->children) {
            pair.second->fail = root;
            q.push(pair.second);
        }

        while (!q.empty()) {
            Node* curr = q.front();
            q.pop();

            for (auto& pair : curr->children) {
                char c = pair.first;
                Node* child = pair.second;
                Node* f = curr->fail;

                while (f != nullptr && f->children.find(c) == f->children.end()) {
                    f = f->fail;
                }

                child->fail = (f == nullptr) ? root : f->children[c];

                // Inherit match from suffix link if this node has no match
                if (child->match_len == 0 && child->fail && child->fail->match_len > 0) {
                    child->match_len = child->fail->match_len;
                }

                q.push(child);
            }
        }
    }

    // Returns (start, length) pairs of matched regions in original text (case-insensitive)
    std::vector<std::pair<size_t, size_t>> search(const std::string& text) {
        std::vector<std::pair<size_t, size_t>> matches;
        Node* curr = root;
        for (size_t i = 0; i < text.size(); ++i) {
            // Lowercase the query character for case-insensitive traversal
            char c = (char)std::tolower((unsigned char)text[i]);
            while (curr != nullptr && curr->children.find(c) == curr->children.end()) {
                curr = curr->fail;
            }
            curr = (curr == nullptr) ? root : curr->children[c];

            Node* temp = curr;
            while (temp != root && temp != nullptr) {
                if (temp->match_len > 0) {
                    matches.push_back({i + 1 - temp->match_len, temp->match_len});
                }
                temp = temp->fail;
            }
        }
        return matches;
    }
};

// --- Egress Firewall Component ---
class EgressFirewall {
private:
    AhoCorasick ac;

    std::string redact_keywords(const std::string& text) {
        auto matches = ac.search(text);
        if (matches.empty()) return text;

        std::vector<std::pair<size_t, size_t>> merged;
        std::sort(matches.begin(), matches.end());

        for (const auto& m : matches) {
            if (merged.empty()) {
                merged.push_back(m);
            } else {
                auto& last = merged.back();
                if (m.first <= last.first + last.second) {
                    last.second = std::max(last.second, m.first + m.second - last.first);
                } else {
                    merged.push_back(m);
                }
            }
        }

        std::string result;
        size_t last_idx = 0;
        for (const auto& m : merged) {
            result += text.substr(last_idx, m.first - last_idx);
            result += "***REDACTED***";
            last_idx = m.first + m.second;
        }
        result += text.substr(last_idx);
        return result;
    }

    std::string redact_ips(const std::string& text) {
        static const std::regex ip_regex(
            "\\b(10\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}|"
            "192\\.168\\.\\d{1,3}\\.\\d{1,3}|"
            "172\\.(1[6-9]|2\\d|3[0-1])\\.\\d{1,3}\\.\\d{1,3})\\b"
        );
        return std::regex_replace(text, ip_regex, "[IP REDACTED]");
    }

public:
    EgressFirewall() {
        // Patterns are stored lowercase inside AhoCorasick for case-insensitive matching
        std::vector<std::string> blacklist = {
            "BetaGraph", "Aegis Phoenix", "Phoenix",
            "Acquisition", "Merger", "secret_key"
        };
        for (const auto& word : blacklist) {
            ac.insert(word);
        }
        ac.build();
    }

    // Sliding-window stream processor.
    // Appends new_chunk to pending, applies redaction on the full buffer,
    // then emits everything EXCEPT the last (max_pattern_len - 1) bytes so that
    // keywords split across SSE boundaries are always seen whole.
    // On is_final=true flushes everything and clears pending.
    std::string process_stream(std::string& pending, const std::string& new_chunk, bool is_final, int clearance_level) {
        pending += new_chunk;

        // Apply keyword redaction only for non-executive clearance
        std::string redacted = pending;
        if (clearance_level < 3) {
            redacted = redact_keywords(redacted);
        }
        redacted = redact_ips(redacted);

        if (is_final) {
            pending.clear();
            return redacted;
        }

        // Hold back the last (max_pattern_len - 1) characters to catch cross-chunk keywords.
        // If the buffer is shorter than the hold-back window, emit nothing yet.
        size_t hold = (ac.max_pattern_len > 0) ? ac.max_pattern_len - 1 : 0;
        if (redacted.size() <= hold) {
            pending = redacted; // keep entire buffer, emit nothing
            return "";
        }

        std::string to_emit = redacted.substr(0, redacted.size() - hold);
        pending = redacted.substr(redacted.size() - hold);
        return to_emit;
    }
};

int main() {
    httplib::Server svr;

    std::cout << "[Gateway] Initializing C++ Ingress & Egress Security Gateway..." << std::endl;

    svr.Get("/health", [](const httplib::Request&, httplib::Response& res) {
        json status = {
            {"status", "healthy"},
            {"engine", "C++ Ingress Gateway"},
            {"downstream", "http://" + PYTHON_HOST + ":" + std::to_string(PYTHON_PORT)}
        };
        res.set_content(status.dump(), "application/json");
    });

    svr.Post("/auth/login", [](const httplib::Request& req, httplib::Response& res) {
        try {
            auto body = json::parse(req.body);
            std::string role = body.value("role", "intern");

            auto token = jwt::create()
                .set_issuer("aegis_gateway")
                .set_type("JWT")
                .set_payload_claim("org_id", jwt::claim(std::string("org_alpha")))
                .set_issued_at(std::chrono::system_clock::now())
                .set_expires_at(std::chrono::system_clock::now() + std::chrono::hours{1});

            if (role == "intern") {
                token.set_payload_claim("clearance_level", picojson::value(int64_t(1)));
                token.set_payload_claim("departments", jwt::claim(std::set<std::string>{"Engineering"}));
                token.set_payload_claim("projects", jwt::claim(std::set<std::string>{}));
            } else if (role == "engineer") {
                token.set_payload_claim("clearance_level", picojson::value(int64_t(2)));
                token.set_payload_claim("departments", jwt::claim(std::set<std::string>{"Engineering"}));
                token.set_payload_claim("projects", jwt::claim(std::set<std::string>{"CoreEngine"}));
            } else if (role == "hr") {
                token.set_payload_claim("clearance_level", picojson::value(int64_t(2)));
                token.set_payload_claim("departments", jwt::claim(std::set<std::string>{"HR"}));
                token.set_payload_claim("projects", jwt::claim(std::set<std::string>{"CompensationReview"}));
            } else if (role == "executive") {
                token.set_payload_claim("clearance_level", picojson::value(int64_t(3)));
                token.set_payload_claim("departments", jwt::claim(std::set<std::string>{"Executive", "Finance", "Engineering"}));
                token.set_payload_claim("projects", jwt::claim(std::set<std::string>{"Mergers", "CoreEngine"}));
            } else {
                res.status = 400;
                res.set_content("{\"error\":\"Invalid role requested\"}", "application/json");
                return;
            }

            std::string signed_jwt = token.sign(jwt::algorithm::hs256{SHARED_SECRET});
            json resp = {
                {"token", signed_jwt},
                {"role", role},
                {"expires_in_seconds", 3600}
            };
            res.set_content(resp.dump(), "application/json");
        } catch (const std::exception& e) {
            res.status = 400;
            res.set_content(std::string("{\"error\":\"JSON parsing failed: ") + e.what() + "\"}", "application/json");
        }
    });

    svr.Post("/api/query", [&](const httplib::Request& req, httplib::Response& res) {
        std::string auth_header = req.get_header_value("Authorization");
        if (auth_header.empty() || auth_header.size() < 8 || auth_header.substr(0, 7) != "Bearer ") {
            res.status = 401;
            res.set_content("{\"error\":\"Unauthorized: Missing or malformed Authorization header\"}", "application/json");
            return;
        }

        std::string token_str = auth_header.substr(7);

        try {
            auto decoded = jwt::decode(token_str);
            auto verifier = jwt::verify()
                .allow_algorithm(jwt::algorithm::hs256{SHARED_SECRET})
                .with_issuer("aegis_gateway");
            verifier.verify(decoded);

            httplib::Headers headers;
            headers.emplace("Content-Type", "application/json");
            headers.emplace("Authorization", "Bearer " + token_str);

            auto queue = std::make_shared<SafeQueue>();

            // Detached background thread drives client call and pushes to queue
            std::thread([queue, headers, req_body = req.body]() {
                httplib::Client cli(PYTHON_HOST, PYTHON_PORT);
                cli.set_keep_alive(true);

                httplib::Request downstream_req;
                downstream_req.method = "POST";
                downstream_req.path = "/api/query";
                downstream_req.headers = headers;
                downstream_req.body = req_body;
                downstream_req.content_receiver = [queue](const char *data, size_t data_len, uint64_t, uint64_t) {
                    queue->push(std::string(data, data_len));
                    return true;
                };

                cli.send(downstream_req);
                queue->finish();
            }).detach();

            res.set_chunked_content_provider("text/event-stream",
                [queue](size_t /*offset*/, httplib::DataSink &sink) {
                    std::string chunk;
                    if (queue->pop(chunk)) {
                        sink.write(chunk.data(), chunk.size());
                        return true;
                    }
                    sink.done();
                    return false;
                }
            );
        } catch (const std::exception& e) {
            res.status = 401;
            res.set_content(std::string("{\"error\":\"Unauthorized: ") + e.what() + "\"}", "application/json");
        }
    });

    std::cout << "[Gateway] Server listening on http://0.0.0.0:8080" << std::endl;
    svr.listen("0.0.0.0", 8080);
    return 0;
}
