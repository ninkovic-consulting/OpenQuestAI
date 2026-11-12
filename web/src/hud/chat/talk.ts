// Push to talk from two places, Space and the hold-to-talk control. Whichever
// pressed first owns the hold, so the other cannot end it early.

export type TalkHand = "key" | "pointer";

export class Talk {
  private hand: TalkHand | null = null;

  constructor(private readonly send: (down: boolean) => void) {}

  get held(): boolean {
    return this.hand !== null;
  }

  down(hand: TalkHand): void {
    if (this.hand !== null) return;
    this.hand = hand;
    this.send(true);
  }

  up(hand: TalkHand): void {
    if (this.hand !== hand) return;
    this.hand = null;
    this.send(false);
  }

  /** The window lost focus: whatever was held is let go. */
  cancel(): void {
    if (this.hand !== null) this.up(this.hand);
  }
}
