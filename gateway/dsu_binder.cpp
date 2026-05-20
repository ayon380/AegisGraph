#include <iostream>
#include <string>
#include <vector>
#include <unordered_map>
#include <algorithm>
#include <cmath>
#include <cctype>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

// --- DSU Structure for clustering disjoint components ---
struct DSU {
    std::vector<int> parent;
    std::vector<int> rank;

    DSU(int n) {
        parent.resize(n);
        rank.resize(n, 0);
        for (int i = 0; i < n; ++i) {
            parent[i] = i;
        }
    }

    int find(int i) {
        if (parent[i] == i)
            return i;
        return parent[i] = find(parent[i]); // Path compression
    }

    void union_sets(int i, int j) {
        int root_i = find(i);
        int root_j = find(j);
        if (root_i != root_j) {
            if (rank[root_i] < rank[root_j]) {
                parent[root_i] = root_j;
            } else if (rank[root_i] > rank[root_j]) {
                parent[root_j] = root_i;
            } else {
                parent[root_j] = root_i;
                rank[root_i]++;
            }
        }
    }
};

// --- High-Performance Jaro-Winkler Distance Implementation ---
double jaro_winkler_distance(const std::string& s1, const std::string& s2) {
    int len1 = s1.length();
    int len2 = s2.length();
    if (len1 == 0 && len2 == 0) return 1.0;
    if (len1 == 0 || len2 == 0) return 0.0;

    int match_distance = std::max(len1, len2) / 2 - 1;
    if (match_distance < 0) match_distance = 0;

    std::vector<bool> s1_matches(len1, false);
    std::vector<bool> s2_matches(len2, false);

    int matches = 0;
    for (int i = 0; i < len1; ++i) {
        int start = std::max(0, i - match_distance);
        int end = std::min(len2 - 1, i + match_distance);
        for (int j = start; j <= end; ++j) {
            if (!s2_matches[j] && s1[i] == s2[j]) {
                s1_matches[i] = true;
                s2_matches[j] = true;
                matches++;
                break;
            }
        }
    }

    if (matches == 0) return 0.0;

    double transpositions = 0;
    int k = 0;
    for (int i = 0; i < len1; ++i) {
        if (s1_matches[i]) {
            while (!s2_matches[k]) k++;
            if (s1[i] != s2[k]) transpositions++;
            k++;
        }
    }

    double jaro = (double(matches) / len1 + double(matches) / len2 + (matches - transpositions / 2.0) / matches) / 3.0;

    // Winkler extension (prefix match scale)
    double p = 0.1;
    int prefix_len = 0;
    for (int i = 0; i < std::min({len1, len2, 4}); ++i) {
        if (s1[i] == s2[i]) prefix_len++;
        else break;
    }

    return jaro + prefix_len * p * (1.0 - jaro);
}

// --- Acronym Validation Engine ("AWS" vs "Amazon Web Services") ---
bool is_acronym(const std::string& s_short, const std::string& s_long) {
    if (s_short.empty() || s_long.empty()) return false;
    
    // Clean short string (keep letters, convert to uppercase)
    std::string clean_short = "";
    for (char c : s_short) {
        if (std::isalnum(c)) clean_short += std::toupper(c);
    }
    if (clean_short.size() < 2) return false;
    
    // Compile initials of long string
    std::string initials = "";
    bool new_word = true;
    for (char c : s_long) {
        if (std::isspace(c) || c == '-' || c == '_') {
            new_word = true;
        } else if (new_word) {
            if (std::isalnum(c)) {
                initials += std::toupper(c);
                new_word = false;
            }
        }
    }
    
    return clean_short == initials;
}

// --- Multi-Entity Canonicalization Entry Point ---
std::unordered_map<std::string, std::string> canonicalize(const std::vector<std::string>& entities, double threshold) {
    int n = entities.size();
    DSU dsu(n);

    for (int i = 0; i < n; ++i) {
        for (int j = i + 1; j < n; ++j) {
            double sim = jaro_winkler_distance(entities[i], entities[j]);
            
            // Check acronym equivalence if standard similarity is low
            if (sim < threshold) {
                if (is_acronym(entities[i], entities[j]) || is_acronym(entities[j], entities[i])) {
                    sim = 1.0;
                }
            }

            if (sim >= threshold) {
                dsu.union_sets(i, j);
            }
        }
    }

    // Determine the optimal representative (longest string for maximum detail)
    std::unordered_map<int, int> root_to_best_idx;
    for (int i = 0; i < n; ++i) {
        int root = dsu.find(i);
        if (root_to_best_idx.find(root) == root_to_best_idx.end()) {
            root_to_best_idx[root] = i;
        } else {
            int current_best = root_to_best_idx[root];
            if (entities[i].length() > entities[current_best].length()) {
                root_to_best_idx[root] = i;
            }
        }
    }

    // Map each original entity name to its cluster representative
    std::unordered_map<std::string, std::string> mapping;
    for (int i = 0; i < n; ++i) {
        int root = dsu.find(i);
        int best_idx = root_to_best_idx[root];
        mapping[entities[i]] = entities[best_idx];
    }

    return mapping;
}

// --- Bindings ---
PYBIND11_MODULE(aegis_dsu, m) {
    m.doc() = "AegisGraph high-performance DSU entity resolution & similarity engine";
    m.def("canonicalize", &canonicalize, "Canonicalizes an entity name list, returning a mapping of original->canonical representation",
          py::arg("entities"), py::arg("threshold") = 0.85);
}
