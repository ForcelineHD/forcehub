<?php
require __DIR__ . '/auth.php';

$res = @file_get_contents(OLLAMA_URL . '/api/tags');

if ($res === false) {
    json_response(['error' => 'Ollama not reachable'], 500);
}

$data = json_decode($res, true);
json_response($data ?: ['error' => 'Invalid Ollama response'], $data ? 200 : 500);
