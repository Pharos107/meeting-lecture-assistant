// Chép core FFmpeg.wasm bản ESM đơn luồng và worker của @ffmpeg/ffmpeg vào public/ffmpeg.
// Worker phải chạy bản chưa bundle: webpack biến import(coreURL) trong worker thành module không tìm thấy.
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const core = join(root, "node_modules", "@ffmpeg", "core", "dist", "esm");
const worker = join(root, "node_modules", "@ffmpeg", "ffmpeg", "dist", "esm");
const target = join(root, "public", "ffmpeg");
const files = [
  [core, "ffmpeg-core.js"],
  [core, "ffmpeg-core.wasm"],
  [worker, "worker.js"],
  [worker, "const.js"],
  [worker, "errors.js"],
];

mkdirSync(target, { recursive: true });
for (const [source, name] of files) {
  const from = join(source, name);
  if (!existsSync(from)) {
    console.warn(`Thiếu ${from}. Trình duyệt sẽ tải file gốc lên thay vì nén.`);
    continue;
  }
  copyFileSync(from, join(target, name));
}
