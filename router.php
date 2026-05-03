<?php
$path = parse_url($_SERVER["REQUEST_URI"], PHP_URL_PATH);

if (str_starts_with($path, "/api/")) {
    $file = __DIR__ . $path;
    if (is_file($file)) {
        require $file;
        return;
    }

    http_response_code(404);
    header("Content-Type: application/json");
    echo json_encode(["error" => "API not found"]);
    return;
}

$file = __DIR__ . "/public" . $path;

if ($path !== "/" && is_file($file)) {
    return false;
}

require __DIR__ . "/public/index.html";
