// Nén file sang Opus 16 kHz mono 32 kb/s trên trình duyệt. Kiến trúc mục 2.1.
// Lỗi ở đây không chặn tải lên: form chuyển sang gửi file gốc.

const CORE_BASE = "/ffmpeg";
const INPUT_DIR = "/input";
const OUTPUT = "output.opus";

export const OPUS_LIMIT_BYTES = 64 * 1024 * 1024;
export const ORIGINAL_LIMIT_BYTES = 500 * 1024 * 1024;

export function isOpusFile(file: File) {
  return /\.(ogg|opus)$/i.test(file.name);
}

function opusName(name: string) {
  const stem = name.replace(/\.[^.]+$/, "") || "audio";
  return `${stem}.opus`;
}

export async function compressToOpus(
  file: File,
  onProgress?: (ratio: number) => void,
  signal?: AbortSignal,
): Promise<File> {
  const { FFmpeg, FFFSType } = await import("@ffmpeg/ffmpeg");
  const ffmpeg = new FFmpeg();
  const abort = () => ffmpeg.terminate();
  signal?.addEventListener("abort", abort, { once: true });
  try {
    // URL tuyệt đối: webpack thay import.meta.url trong thư viện bằng đường dẫn file:// lúc build.
    const base = new URL(CORE_BASE + "/", window.location.origin).href;
    await ffmpeg.load({
      classWorkerURL: `${base}worker.js`,
      coreURL: `${base}ffmpeg-core.js`,
      wasmURL: `${base}ffmpeg-core.wasm`,
    });
    ffmpeg.on("progress", ({ progress }) => {
      if (Number.isFinite(progress)) onProgress?.(Math.min(1, Math.max(0, progress)));
    });
    // WORKERFS đọc thẳng từ File, không chép cả file vào bộ nhớ WASM.
    await ffmpeg.createDir(INPUT_DIR);
    await ffmpeg.mount(FFFSType.WORKERFS, { files: [file] }, INPUT_DIR);
    const code = await ffmpeg.exec([
      "-i",
      `${INPUT_DIR}/${file.name}`,
      "-vn",
      "-ac",
      "1",
      "-ar",
      "16000",
      "-c:a",
      "libopus",
      "-b:a",
      "32k",
      "-f",
      "ogg",
      OUTPUT,
    ]);
    if (code !== 0) throw new Error(`ffmpeg thoát với mã ${code}`);
    const data = await ffmpeg.readFile(OUTPUT);
    if (typeof data === "string" || data.byteLength === 0) throw new Error("ffmpeg không tạo được file Opus");
    return new File([new Uint8Array(data)], opusName(file.name), { type: "audio/ogg" });
  } finally {
    signal?.removeEventListener("abort", abort);
    ffmpeg.terminate();
  }
}
