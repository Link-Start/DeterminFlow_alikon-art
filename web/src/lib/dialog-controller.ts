/** One active dialog across the application. Repeated requests never form a queue. */
export class DialogController<T> {
  private active: { key: string; content: T; promise: Promise<unknown>; resolve: (value: unknown) => void } | null = null;
  private listeners = new Set<() => void>();

  getSnapshot = () => this.active;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  open<R>(key: string, content: T): Promise<R | null> {
    if (this.active) {
      return this.active.key === key
        ? this.active.promise as Promise<R | null>
        : Promise.resolve(null);
    }
    let resolve!: (value: unknown) => void;
    const promise = new Promise<unknown>((done) => { resolve = done; });
    this.active = { key, content, promise, resolve };
    this.emit();
    return promise as Promise<R | null>;
  }

  settle(key: string, value: unknown = null, content?: T): void {
    const active = this.active;
    if (!active || active.key !== key || (content !== undefined && active.content !== content)) return;
    this.active = null;
    active.resolve(value);
    this.emit();
  }

  cancelMatching(prefix: string): void {
    if (this.active?.key.startsWith(prefix)) this.settle(this.active.key);
  }

  private emit(): void { for (const listener of this.listeners) listener(); }
}
