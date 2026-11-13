// Push to talk from several places: Space and the hold-to-talk control, and in
// the widget the Mac app's global shortcut. Whichever pressed first owns the
// hold, so another cannot end it early.

export type TalkHand = "key" | "pointer" | "shortcut";

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
