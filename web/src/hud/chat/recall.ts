// Up in an empty field brings back the last message sent from this window.

/** The messages sent from this window, for Up to recall the last one. */
export class SentLog {
  private last = "";

  remember(text: string): void {
    this.last = text;
  }

  recall(): string {
    return this.last;
  }
}
