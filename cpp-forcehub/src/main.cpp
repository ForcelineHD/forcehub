#include "crow.h"
#include <curl/curl.h>
#include <string>

static size_t write_cb(void* contents, size_t size, size_t nmemb, std::string* out) {
    out->append((char*)contents, size * nmemb);
    return size * nmemb;
}

std::string http_get(const std::string& url) {
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

std::string http_post(const std::string& url, const std::string& body) {
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

int main() {
    curl_global_init(CURL_GLOBAL_DEFAULT);

    crow::SimpleApp app;

    CROW_ROUTE(app, "/")([] {
        return "ForceHub C++ is running";
    });

    CROW_ROUTE(app, "/api/health")([] {
        return crow::response(200, R"({"status":"ok","service":"forcehub-cpp"})");
    });

    CROW_ROUTE(app, "/api/models")([] {
        auto res = http_get("http://127.0.0.1:11434/api/tags");
        return crow::response(200, res);
    });

    CROW_ROUTE(app, "/api/chat").methods(crow::HTTPMethod::POST)
    ([](const crow::request& req) {
        std::string res = http_post(
            "http://127.0.0.1:11434/api/generate",
            req.body
        );

        return crow::response(200, res);
    });

    app.port(9090).bindaddr("127.0.0.1").multithreaded().run();

    curl_global_cleanup();
}
