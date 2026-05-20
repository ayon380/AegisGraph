cmake_minimum_required(VERSION 3.15)
set(CMAKE_POLICY_VERSION_MINIMUM 3.5)
project(aegis_gateway CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Resolve Homebrew OpenSSL path on Apple Silicon macOS
if(APPLE)
    list(APPEND CMAKE_PREFIX_PATH "/opt/homebrew/opt/openssl@3")
endif()

find_package(OpenSSL REQUIRED)

include(FetchContent)

# 1. Fetch cpp-httplib
FetchContent_Declare(
    httplib
    GIT_REPOSITORY https://github.com/yhirose/cpp-httplib.git
    GIT_TAG v0.15.3
)

# 2. Fetch jwt-cpp
FetchContent_Declare(
    jwt-cpp
    GIT_REPOSITORY https://github.com/thalhammer/jwt-cpp.git
    GIT_TAG v0.6.0
)

# 3. Fetch nlohmann/json
FetchContent_Declare(
    json
    GIT_REPOSITORY https://github.com/nlohmann/json.git
    GIT_TAG v3.11.2
)

# 4. Fetch pybind11
FetchContent_Declare(
    pybind11
    GIT_REPOSITORY https://github.com/pybind/pybind11.git
    GIT_TAG v2.10.4
)

FetchContent_MakeAvailable(httplib jwt-cpp json pybind11)

# Find Python for pybind11 build
find_package(Python COMPONENTS Interpreter Development REQUIRED)

# Build Target 1: The Gateway Ingress & Streaming Firewall executable
add_executable(gateway main.cpp)
target_link_libraries(gateway PRIVATE
    OpenSSL::SSL
    OpenSSL::Crypto
    httplib::httplib
    jwt-cpp
    nlohmann_json::nlohmann_json
)

# Build Target 2: The high-performance DSU Entity canonicalization library for Python
pybind11_add_module(aegis_dsu dsu_binder.cpp)   
target_link_libraries(aegis_dsu PRIVATE
    nlohmann_json::nlohmann_json
)
