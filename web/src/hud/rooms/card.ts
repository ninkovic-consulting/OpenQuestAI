// The card shown while the camera is inside a room: its current setup (who
// runs it, on which model, the project's name, the project folders, the tools), what is happening
// there now and the last jobs, a field to give the room's agent a job, and
// "Edit room". It follows the room the selection names.

import type { JobsApi } from "../../net/jobs-api";
import type { Store } from "../../net/store";
import { el } from "../dom";
import { briefField } from "./brief";
import { happening, recent, setup, tools } from "./card-parts";
import { keepKeys } from "./keep-keys";
import { roomCardModel, selectionIn } from "./model";
import type { RoomSelection } from "./selection";

export interface RoomCardDeps {
  store: Store;
  jobs: JobsApi;
  selection: RoomSelection;
  /** Opens Settings, Rooms at this room. */
  onEdit(roomId: string): void;
  /** Opens this job in the Jobs panel. */
  onOpenJob(jobId: string): void;
}

/** Clear space kept between the card and the room beside it. */
const COVER_MARGIN = 16;

/** From this scene width the chat dock moves right of the card; below it the card ends above the dock. */
const BESIDE_PX = 1000;

const kicker = (text: string): HTMLElement => el("div", "caps kicker", text);

export interface RoomCard {
  /** How far from the scene's left edge the card reaches, with a margin; 0 while it is hidden. */
  cover(): number;
}

export function mountRoomCard(parent: HTMLElement, deps: RoomCardDeps): RoomCard {
  const { store, selection } = deps;
  const card = el("section", "room-card");
  card.hidden = true;
  card.setAttribute("aria-label", "Room");
  keepKeys(card);

  const title = el("h2");
  const edit = el("button", "card-edit caps", "Edit room");
  edit.type = "button";
  const head = el("div", "card-head");
  const names = el("div");
  names.append(kicker("Room"), title);
  head.append(names, edit);
  const setupSlot = el("div");
  const nowSlot = el("div", "card-section");
  const briefSlot = el("div", "card-section");
  const toolsSlot = el("div", "card-section");
  const recentSlot = el("div", "card-section");
  card.append(head, setupSlot, nowSlot, briefSlot, toolsSlot, recentSlot);
  parent.append(card);

  let shown: string | null = null;
  /** What the job field was built for; it is kept while this holds, so a draft survives the board's changes. */
  let briefKey = "";
  /** What was last drawn, so a change that is not this room's leaves the focus where it is. */
  let drawn = "";

  edit.addEventListener("click", () => {
    if (shown) deps.onEdit(shown);
  });

  const render = (): void => {
    const s = store.get();
    const id = selectionIn(s.plan, selection.get());
    const model = id && s.plan ? roomCardModel(s.plan, s, id, Date.now() / 1000) : null;
    card.hidden = model === null;
    if (!model || !s.plan) {
      shown = null;
      briefKey = "";
      drawn = "";
      return layout();
    }
    const sig = JSON.stringify([model, s.plan.assistant.name]);
    if (sig === drawn) return layout();
    drawn = sig;
    if (shown !== model.id) card.scrollTop = 0;
    shown = model.id;
    title.textContent = model.name;
    setupSlot.replaceChildren(setup(model, () => deps.onEdit(model.id)));
    nowSlot.replaceChildren(kicker("Happening now"), happening(model, deps.onOpenJob));
    toolsSlot.replaceChildren(kicker("Tools"), ...tools(model));
    recentSlot.replaceChildren(kicker("Recent jobs"), recent(model, deps.onOpenJob));
    const key = JSON.stringify([model.id, model.agent.id, model.agent.name, model.brief?.careful, s.plan.assistant.name]);
    if (key === briefKey) return layout();
    briefKey = key;
    briefSlot.replaceChildren(
      model.brief
        ? briefField(deps.jobs, store, {
            agent: model.agent.id,
            agentName: model.agent.name,
            room: model.id,
            roomName: model.name,
            careful: model.brief.careful,
            host: s.plan.assistant.name,
          })
        : el("p", "note", `${model.agent.name} is spoken to in the chat, and hands work to the others.`),
    );
    layout();
  };

  /** Keeps the card and the chat dock apart: beside each other on a wide scene, one above the other on a narrow one. */
  let watched: Element | null = null;
  const layout = (): void => {
    const chat = parent.querySelector<HTMLElement>(".chat");
    if (chat && chat !== watched) {
      watched = chat;
      new ResizeObserver(layout).observe(chat);
    }
    const beside = parent.clientWidth >= BESIDE_PX;
    parent.style.setProperty("--card-cover", beside && !card.hidden ? `${card.offsetLeft + card.offsetWidth + COVER_MARGIN}px` : "0px");
    const top = [...(chat?.children ?? [])].find((c): c is HTMLElement => c instanceof HTMLElement && c.offsetHeight > 0);
    if (beside || !chat || !top) card.style.maxHeight = "";
    else card.style.maxHeight = `${Math.max(160, chat.offsetTop + top.offsetTop - card.offsetTop - COVER_MARGIN)}px`;
  };
  new ResizeObserver(layout).observe(parent);

  selection.subscribe(render);
  store.subscribe((s, prev) => {
    if (s.plan !== prev.plan || s.jobs !== prev.jobs || s.agents !== prev.agents) render();
  });
  render();
  return { cover: () => (card.hidden ? 0 : card.offsetLeft + card.offsetWidth + COVER_MARGIN) };
}
