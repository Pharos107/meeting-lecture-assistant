// Chạy chữ theo nhịp xử lý của worker. Kiến trúc mục 2.6.

export const MIN_DELAY = 40;
export const MAX_DELAY = 180;
export const FLUSH_DELAY = 15;

export class AdaptiveTypewriter<T> {
  private queue: T[] = [];
  private delay = MIN_DELAY;
  private running = false;
  private finished = false;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private nextAt = 0;

  constructor(private readonly onItem: (item: T) => void) {}

  /** Nhịp tính một lần cho cả cụm, không chia lại theo số từ còn lại. */
  enqueueChunk(items: T[], expectedNextMs: number) {
    const count = items.length;
    this.queue.push(...items);
    if (count > 0) {
      const raw = expectedNextMs / count;
      this.delay = Math.max(MIN_DELAY, Math.min(MAX_DELAY, raw));
    }
    if (this.queue.length > count * 2) {
      this.delay = MIN_DELAY;
    }
    this.kick();
  }

  markStreamComplete() {
    this.finished = true;
    this.delay = FLUSH_DELAY;
    this.kick();
  }

  /** Dừng hẳn, bỏ phần còn tồn. Dùng khi rời trang. */
  dispose() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.queue = [];
    this.running = false;
  }

  get pending() {
    return this.queue.length;
  }

  private kick() {
    if (this.running) return;
    this.running = true;
    this.nextAt = performance.now();
    this.tick();
  }

  private tick() {
    const item = this.queue.shift();
    if (item === undefined) {
      this.running = false;
      this.timer = null;
      return;
    }
    this.onItem(item);
    // Hẹn theo mốc tuyệt đối để độ trễ của timer không cộng dồn qua từng từ.
    this.nextAt += this.finished ? FLUSH_DELAY : this.delay;
    this.timer = setTimeout(() => this.tick(), Math.max(0, this.nextAt - performance.now()));
  }
}
