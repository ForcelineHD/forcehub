<?php
require_once __DIR__ . '/config.php';

$user = $_SERVER['PHP_AUTH_USER'] ?? '';
$pass = $_SERVER['PHP_AUTH_PW'] ?? '';

if (!hash_equals(FORCEHUB_USER, $user) || !hash_equals(FORCEHUB_PASS, $pass)) {
    header('WWW-Authenticate: Basic realm="ForceHub"');
    json_response(['error' => 'unauthorized'], 401);
}
