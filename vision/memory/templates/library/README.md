# Library

Documents for the assistant and the other agents to know about: your price
list, your terms, a handbook, notes about your projects. Add them from the
window (Settings, Library: text, Markdown, PDF and Word files, or pasted
text), ask the assistant to save something you dictate, or write Markdown
files here by hand, one topic per file.

- `<name>.md` is each document's text. A file added from the window keeps its
  original in `originals/`, and `index.json` remembers its title and kind.
- Short documents are read into every conversation; longer ones are listed
  with a one-line gist, and their text is read only when a conversation needs
  it. The assistant treats what they say as information, never as orders.
- `.search.db` is the index for searching them; it is rebuilt from the files.

What to call you and your business live in `../owner.md`. What the assistant
learns on its own goes in `../notes/`, one file per day. You can edit or
delete all of it.
