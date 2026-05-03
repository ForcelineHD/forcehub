cmake_minimum_required(VERSION 3.16)
project(forcehub_cpp)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(forcehub_cpp src/main.cpp)

find_package(Threads REQUIRED)
find_package(CURL REQUIRED)

target_include_directories(forcehub_cpp PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/external/Crow/include
)

target_link_libraries(forcehub_cpp PRIVATE Threads::Threads CURL::libcurl)
