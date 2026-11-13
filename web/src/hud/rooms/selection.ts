// The room the owner is looking at, shared by the scene, the card, the
// agents' lists and the labels. The scene is the only one that moves the
// camera; it reports the room it flew into here.

export type SelectionListener = (room: string | null) => void;

export class RoomSelection {
  private room: string | null = null;
  private readonly listeners = new Set<SelectionListener>();

  get(): string | null {
    return this.room;
  }

  set(room: string | null): void {
    if (room === this.room) return;
    this.room = room;
    for (const l of this.listeners) l(room);
  }

  subscribe(listener: SelectionListener): void {
    this.listeners.add(listener);
  }
}
