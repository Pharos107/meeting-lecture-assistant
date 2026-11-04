// Hạ mẫu về 16 kHz mono và gửi khung PCM s16le 100 ms (1600 mẫu). Kiến trúc mục 3.1.
const TARGET_RATE = 16000;
const FRAME_SAMPLES = 1600;

class PcmFrameProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.step = sampleRate / TARGET_RATE;
    this.position = 0;
    this.sum = 0;
    this.count = 0;
    this.frame = new Int16Array(FRAME_SAMPLES);
    this.filled = 0;
  }

  push(value) {
    const clamped = Math.max(-1, Math.min(1, value));
    this.frame[this.filled++] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
    if (this.filled === FRAME_SAMPLES) {
      this.port.postMessage(this.frame.buffer, [this.frame.buffer]);
      this.frame = new Int16Array(FRAME_SAMPLES);
      this.filled = 0;
    }
  }

  process(inputs) {
    const channels = inputs[0];
    if (!channels || channels.length === 0) return true;
    const length = channels[0].length;
    for (let index = 0; index < length; index += 1) {
      let mixed = 0;
      for (const channel of channels) mixed += channel[index];
      // Lấy trung bình các mẫu rơi vào một mẫu 16 kHz, đủ chặn răng cưa cho tiếng nói.
      this.sum += mixed / channels.length;
      this.count += 1;
      this.position += 1;
      if (this.position >= this.step) {
        this.push(this.sum / this.count);
        this.position -= this.step;
        this.sum = 0;
        this.count = 0;
      }
    }
    return true;
  }
}

registerProcessor("pcm-frame-processor", PcmFrameProcessor);
