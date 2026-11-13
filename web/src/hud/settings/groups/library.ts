// The Library group: the owner's documents. Add files by choosing or
// dropping them, or paste text with a title; open one to read its text,
// rename it, remove it after a confirmation. Every change applies at once,
// and a refusal is shown beside the action that drew it.

import type { LibraryApi } from "../../../net/library-api";
import type { LibraryDocument, LibraryListing } from "../../../net/library-types";
import { el, setText } from "../../dom";
import type { Group } from "../context";
import { block, button, confirmButton, fieldRow, note, statusLine } from "../fields";
import { documentMeta, uploadLine } from "../library-parts";

export const libraryGroup: Group = {
  id: "library",
  title: "Library",
  blurb: "Documents the assistant and the other agents can read: a price list, your terms, a handbook. Short ones are always in mind; longer ones are read when a question needs them.",
  prefixes: [],
  render(ctx) {
    const api = ctx.library;
    const name = ctx.settings.assistant.name;
    const root = el("div", "group-body library");
    let listing: LibraryListing | null = null;
    let opened: string | null = null;

    const adding = el("div", "library-add");
    const uploads = el("ul", "upload-lines");
    uploads.setAttribute("aria-live", "polite");
    const list = el("div", "doc-list");
    const where = el("div");

    const draw = (): void => {
      if (!listing) {
        list.replaceChildren(statusLine("idle", "Loading the library…"));
        return;
      }
      const docs = listing.documents;
      if (opened !== null) {
        const doc = docs.find((d) => d.name === opened);
        if (doc) {
          list.replaceChildren(reader(api, doc, () => close()));
          return;
        }
        opened = null;
      }
      list.replaceChildren(
        docs.length === 0
          ? el("p", "field-note", `No documents yet. Add a file above, paste some text, or ask ${name} to save something you dictate.`)
          : el("p", "field-note", `${docs.length} ${docs.length === 1 ? "document" : "documents"}, newest first.`),
        ...docs.map((d) => row(api, d, { open: () => show(d.name), changed: () => void load() })),
      );
      where.replaceChildren(
        el("p", "field-note", "Each document's text is a Markdown file in this folder, and a file you add is kept as it was in originals/ beside it. You can open, edit or delete them there too."),
        el("code", "library-path", listing.folder),
        el("p", "field-note", `${name} and the other agents can read every document here. Their text goes to the model only when a conversation needs it, and what they say is taken as information, never as instructions.`),
      );
    };

    const show = (doc: string): void => {
      opened = doc;
      draw();
      list.scrollIntoView({ block: "nearest" });
    };
    const close = (): void => {
      opened = null;
      draw();
    };

    const load = async (): Promise<void> => {
      const r = await api.list();
      if (!r.ok) {
        list.replaceChildren(statusLine("bad", `The library could not be loaded: ${r.message}`));
        return;
      }
      listing = r.value;
      chooser.accept = listing.limits.endings.join(",");
      setText(limitsNote, `Text, Markdown, PDF and Word (.docx) files, up to ${Math.round(listing.limits.max_file_bytes / 1048576)} MB each, or pasted text. A scanned PDF has no text to read and is refused.`);
      draw();
    };

    const addFiles = (files: readonly File[]): void => {
      for (const file of files) {
        const line = uploadLine(file.name, "idle", "Adding…");
        uploads.prepend(line.root);
        void api.addFile(file).then((r) => {
          if (r.ok) {
            line.set("ok", `Added as “${r.value.title}”, ${r.value.chars.toLocaleString("en")} characters of text.`);
            void load();
          } else {
            line.set("bad", r.message);
          }
        });
      }
    };

    const chooser = el("input");
    chooser.type = "file";
    chooser.multiple = true;
    chooser.hidden = true;
    chooser.addEventListener("change", () => {
      addFiles(Array.from(chooser.files ?? []));
      chooser.value = "";
    });
    const choose = button("Choose files", "primary");
    choose.addEventListener("click", () => chooser.click());
    const paste = pasteForm(api, () => void load());
    paste.hidden = true;
    const pasteToggle = button("Paste text");
    pasteToggle.setAttribute("aria-expanded", "false");
    pasteToggle.addEventListener("click", () => {
      paste.hidden = !paste.hidden;
      pasteToggle.setAttribute("aria-expanded", String(!paste.hidden));
      if (!paste.hidden) paste.querySelector("input")?.focus();
    });
    const drop = el("div", "drop-zone");
    drop.append(el("span", "caps", "Drop files here"), el("span", "drop-or", "or"), choose, pasteToggle, chooser);
    const limitsNote = note();
    adding.append(drop, limitsNote, uploads, paste);

    // Dropping anywhere on the group adds the files; the zone lights up while something is held over it.
    let depth = 0;
    root.addEventListener("dragenter", (ev) => {
      if (!ev.dataTransfer?.types.includes("Files")) return;
      ev.preventDefault();
      depth += 1;
      root.classList.add("is-dropping");
    });
    root.addEventListener("dragover", (ev) => {
      if (ev.dataTransfer?.types.includes("Files")) ev.preventDefault();
    });
    root.addEventListener("dragleave", () => {
      depth = Math.max(0, depth - 1);
      if (depth === 0) root.classList.remove("is-dropping");
    });
    root.addEventListener("drop", (ev) => {
      if (!ev.dataTransfer?.files.length) return;
      ev.preventDefault();
      depth = 0;
      root.classList.remove("is-dropping");
      addFiles(Array.from(ev.dataTransfer.files));
    });

    root.append(
      block("Add documents", adding),
      block("Documents", list),
      block("Where they live", where),
    );
    draw();
    void load();
    return root;
  },
};

interface RowActions {
  open(): void;
  changed(): void;
}

function row(api: LibraryApi, doc: LibraryDocument, actions: RowActions): HTMLElement {
  const item = el("article", "doc-row");
  const what = el("div", "doc-what");
  const title = el("h5", "doc-title", doc.title);
  what.append(title, documentMeta(doc));
  if (doc.gist) what.append(el("p", "doc-gist", doc.gist));
  const said = el("p", "field-error");
  said.setAttribute("role", "alert");
  said.hidden = true;
  const tools = el("div", "doc-actions");
  const open = button("Open");
  open.addEventListener("click", actions.open);
  const rename = button("Rename");
  rename.addEventListener("click", () => {
    const input = el("input");
    input.value = doc.title;
    input.maxLength = 120;
    input.setAttribute("aria-label", `New title for ${doc.title}`);
    const save = button("Save", "primary");
    const cancel = button("Cancel");
    const form = el("div", "doc-rename");
    form.append(input, save, cancel);
    title.replaceWith(form);
    tools.hidden = true;
    input.focus();
    input.select();
    const done = (): void => {
      form.replaceWith(title);
      tools.hidden = false;
    };
    cancel.addEventListener("click", done);
    const go = (): void => {
      save.disabled = true;
      void api.rename(doc.name, input.value).then((r) => {
        save.disabled = false;
        if (r.ok) {
          actions.changed();
          return;
        }
        said.textContent = r.message;
        said.hidden = false;
      });
    };
    save.addEventListener("click", go);
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") go();
      else if (ev.key === "Escape") {
        ev.stopPropagation();
        done();
      }
    });
  });
  const remove = confirmButton(
    "Remove",
    { question: `Remove “${doc.title}”${doc.original ? " and the file it came from" : ""}? This cannot be undone.`, confirm: "Remove", danger: true },
    async () => {
      const r = await api.remove(doc.name);
      if (r.ok) actions.changed();
      return r.ok ? `Removed “${r.value.title}”.` : r.message;
    },
  );
  tools.append(open, rename, remove);
  item.append(what, tools, said);
  return item;
}

function reader(api: LibraryApi, doc: LibraryDocument, close: () => void): HTMLElement {
  const root = el("div", "doc-reader");
  const head = el("header", "doc-reader-head");
  const titles = el("div");
  titles.append(el("h5", "doc-title", doc.title), documentMeta(doc));
  const back = button("Back to the list");
  back.addEventListener("click", close);
  head.append(titles, back);
  const body = el("pre", "doc-text");
  body.tabIndex = 0;
  body.setAttribute("aria-label", `The text of ${doc.title}`);
  body.append(statusLine("idle", "Opening…"));
  root.append(head, body);
  void api.open(doc.name).then((r) => {
    if (r.ok) body.textContent = r.value.text;
    else body.replaceChildren(statusLine("bad", r.message));
  });
  const keep = el("p", "field-note", doc.original ? `This is the text taken out of the file when it was added; the file itself is kept as ${doc.original}.` : "A written document: the assistant can add to it or change it when you ask.");
  root.append(keep);
  return root;
}

function pasteForm(api: LibraryApi, added: () => void): HTMLElement {
  const root = el("div", "library-paste");
  const title = el("input");
  title.maxLength = 120;
  title.placeholder = "Price list 2027";
  const text = el("textarea");
  text.rows = 5;
  text.placeholder = "Paste or type the text here.";
  const save = button("Save as a document");
  const said = statusSlot();
  save.addEventListener("click", () => {
    save.disabled = true;
    void api.addText(title.value, text.value).then((r) => {
      save.disabled = false;
      if (r.ok) {
        said.show("ok", `Saved “${r.value.title}”.`);
        title.value = "";
        text.value = "";
        added();
      } else {
        said.show("bad", r.message);
      }
    });
  });
  const actions = el("div", "row-actions");
  actions.append(save, said.root);
  root.append(fieldRow("Title", title), fieldRow("Text", text), actions);
  return root;
}

function statusSlot(): { root: HTMLElement; show(tone: "ok" | "bad", text: string): void } {
  const root = el("div", "status-slot");
  return {
    root,
    show(tone, text) {
      root.replaceChildren(statusLine(tone, text));
    },
  };
}
