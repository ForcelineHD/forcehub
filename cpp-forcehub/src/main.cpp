#include "crow.h"
#include <curl/curl.h>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>

namespace fs = std::filesystem;

static fs::path repo_root() {
    return fs::current_path().parent_path();
}

static std::string read_file(const fs::path& path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) return "";
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

static size_t write_cb(void* contents, size_t size, size_t nmemb, std::string* out) {
    out->append((char*)contents, size * nmemb);
    return size * nmemb;
}

static std::string http_get(const std::string& url) {
    CURL* curl = curl_easy_init();
    std::string out;
    if (!curl) return R"({"error":"curl init failed"})";

    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &out);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 30L);

    curl_easy_perform(curl);
    curl_easy_cleanup(curl);
    return out;
}

static std::string http_post(const std::string& url, const std::string& body) {
    CURL* curl = curl_easy_init();
    std::string out;
    if (!curl) return R"({"error":"curl init failed"})";

    struct curl_slist* headers = nullptr;
    headers = curl_slist_append(headers, "Content-Type: application/json");

    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.c_str());
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &out);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 180L);

    curl_easy_perform(curl);
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);
    return out;
}

static bool safe_path(const fs::path& base, const fs::path& target) {
    auto b = fs::weakly_canonical(base).string();
    auto t = fs::weakly_canonical(target).string();
    return t.rfind(b, 0) == 0;
}

int main() {
    curl_global_init(CURL_GLOBAL_DEFAULT);

    crow::SimpleApp app;

    CROW_ROUTE(app, "/")([] {
        auto html = read_file(repo_root() / "public/index.html");
        crow::response res(200, html);
        res.set_header("Content-Type", "text/html; charset=utf-8");
        return res;
    });

    CROW_ROUTE(app, "/css/style.css")([] {
        auto css = read_file(repo_root() / "public/css/style.css");
        crow::response res(200, css);
        res.set_header("Content-Type", "text/css; charset=utf-8");
        return res;
    });

    CROW_ROUTE(app, "/js/app.js")([] {
        auto js = read_file(repo_root() / "public/js/app.js");
        crow::response res(200, js);
        res.set_header("Content-Type", "application/javascript; charset=utf-8");
        return res;
    });

    CROW_ROUTE(app, "/api/health")([] {
        return crow::response(200, R"({"status":"ok","service":"forcehub-cpp"})");
    });

    CROW_ROUTE(app, "/api/models")([] {
        auto res = http_get("http://127.0.0.1:11434/api/tags");
        crow::response r(200, res);
        r.set_header("Content-Type", "application/json");
        return r;
    });

    CROW_ROUTE(app, "/api/chat").methods(crow::HTTPMethod::POST)([](const crow::request& req) {
        auto res = http_post("http://127.0.0.1:11434/api/generate", req.body);
        crow::response r(200, res);
        r.set_header("Content-Type", "application/json");
        return r;
    });

    CROW_ROUTE(app, "/api/files")([](const crow::request& req) {
        auto root = repo_root();
        std::string rel = req.url_params.get("path") ? req.url_params.get("path") : ".";
        auto target = root / rel;

        if (!safe_path(root, target)) {
            return crow::response(400, R"({"error":"invalid path"})");
        }

        crow::json::wvalue out;

        if (fs::is_directory(target)) {
            out["type"] = "dir";
            out["path"] = rel;
            out["items"] = crow::json::wvalue::list();

            int i = 0;
            for (const auto& entry : fs::directory_iterator(target)) {
                auto name = entry.path().filename().string();
                if (name == ".git" || name == ".venv" || name == "data" || name == "__pycache__") continue;

                auto item_rel = fs::relative(entry.path(), root).string();
                out["items"][i]["name"] = name;
                out["items"][i]["path"] = item_rel;
                out["items"][i]["type"] = entry.is_directory() ? "dir" : "file";
                i++;
            }

            return crow::response(out);
        }

        out["type"] = "file";
        out["path"] = rel;
        out["content"] = read_file(target);
        return crow::response(out);
    });

    app.port(9090).bindaddr("127.0.0.1").multithreaded().run();

    curl_global_cleanup();
}
