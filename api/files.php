<?php
require __DIR__ . '/auth.php';

$base = realpath(__DIR__ . '/..');
$rel = $_GET['path'] ?? '.';
$target = realpath($base . '/' . $rel);

if ($target === false || !str_starts_with($target, $base)) {
    json_response(['error' => 'invalid path'], 400);
}

if (is_dir($target)) {
    $items = [];
    foreach (scandir($target) as $item) {
        if ($item === '.' || $item === '..') continue;
        if (in_array($item, ['.git', '.venv', '__pycache__', 'data'], true)) continue;

        $full = $target . '/' . $item;
        $items[] = [
            'name' => $item,
            'path' => ltrim(str_replace($base, '', $full), '/'),
            'type' => is_dir($full) ? 'dir' : 'file'
        ];
    }

    json_response([
        'type' => 'dir',
        'path' => $rel,
        'items' => $items
    ]);
}

$content = file_get_contents($target);
json_response([
    'type' => 'file',
    'path' => $rel,
    'content' => $content === false ? '' : $content
]);
