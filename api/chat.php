<?php
require __DIR__ . '/auth.php';

$raw = file_get_contents('php://input');
$body = json_decode($raw ?: '{}', true);

$prompt = trim($body['prompt'] ?? '');
$model = 'qwen2.5-coder:1.5b';

if ($prompt === '') {
    json_response(['error' => 'missing prompt'], 400);
}

$payload = json_encode([
    'model' => $model,
    'prompt' => $prompt,
    'stream' => false
]);

$ch = curl_init(OLLAMA_URL . '/api/generate');
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_POST => true,
    CURLOPT_HTTPHEADER => ['Content-Type: application/json'],
    CURLOPT_POSTFIELDS => $payload,
    CURLOPT_TIMEOUT => 60,
]);

$res = curl_exec($ch);

if ($res === false) {
    json_response(['error' => curl_error($ch)], 500);
}

$data = json_decode($res, true);

json_response([
    'model' => $model,
    'response' => $data['response'] ?? '',
    'done' => $data['done'] ?? false
]);
