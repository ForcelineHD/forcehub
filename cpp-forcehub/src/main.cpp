#include "crow.h"
#include <filesystem>
#include <fstream>
#include <sstream>

namespace fs = std::filesystem;

std::string read_file(const fs::path& path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) return "";
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

int main() {
    crow::SimpleApp app;


    CROW_ROUTE(app, "/")([] {
        return crow::response(200, "ForceHub C++ is running");
    });

    CROW_ROUTE(app, "/api/health")([] {
        return crow::response(200, R"({"status":"ok","service":"forcehub-cpp"})");
    });

    CROW_ROUTE(app, "/api/models")([] {
        return crow::response(200, R"({"todo":"proxy Ollama /api/tags next"})");
    });

    CROW_ROUTE(app, "/api/files")([] {
        crow::json::wvalue out;
        out["type"] = "dir";
        out["path"] = ".";
        out["items"] = crow::json::wvalue::list();

        int i = 0;
        for (const auto& entry : fs::directory_iterator(fs::current_path().parent_path())) {
            auto name = entry.path().filename().string();
            if (name == ".git" || name == ".venv" || name == "data") continue;

            out["items"][i]["name"] = name;
            out["items"][i]["type"] = entry.is_directory() ? "dir" : "file";
            i++;
        }

        return crow::response(out);
    });

    CROW_ROUTE(app, "/api/chat").methods(crow::HTTPMethod::POST)([](const crow::request& req) {
        crow::json::wvalue out;
        out["response"] = "C++ chat endpoint is alive. Ollama proxy comes next.";
        out["received_bytes"] = static_cast<int>(req.body.size());
        return crow::response(out);
    });

    app.port(9090).bindaddr("127.0.0.1").multithreaded().run();
}
