<?php
declare(strict_types=1);

const FORCEHUB_USER = 'flozi';
const FORCEHUB_PASS = 'forcehub';
const OLLAMA_URL = 'http://127.0.0.1:11434';

function json_response(array $data, int $code = 200): never {
    http_response_code($code);
    header('Content-Type: application/json');
    echo json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
    exit;
}
