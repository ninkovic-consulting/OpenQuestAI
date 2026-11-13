import { describe, expect, it } from "vitest";
import { cleanFolders, foldersNote, limitReason, sameFolders, sameFolderSet, withFolder, withoutFolder } from "./folders";

describe("a room's folder list", () => {
  it("is cleaned of blanks and stray spaces", () => {
    expect(cleanFolders([" ~/a ", "", "  ", "~/b"])).toEqual(["~/a", "~/b"]);
  });

  it("compares in order, or as a set", () => {
    expect(sameFolders(["~/a", "~/b"], ["~/a", "~/b"])).toBe(true);
    expect(sameFolders(["~/a", "~/b"], ["~/b", "~/a"])).toBe(false);
    expect(sameFolderSet(["~/a", "~/b"], ["~/b", "~/a"])).toBe(true);
    expect(sameFolderSet(["~/a"], ["~/a", "~/b"])).toBe(false);
  });

  it("adds a folder at the end, ignoring blank text, and never changes the list it was given", () => {
    const list = ["~/a"];
    expect(withFolder(list, " ~/b ")).toEqual(["~/a", "~/b"]);
    expect(withFolder(list, "  ")).toEqual(["~/a"]);
    expect(withFolder(list, "~/a")).toEqual(["~/a", "~/a"]);
    expect(list).toEqual(["~/a"]);
  });

  it("removes the folder at one place and keeps the others in order", () => {
    expect(withoutFolder(["~/a", "~/b", "~/c"], 1)).toEqual(["~/a", "~/c"]);
    expect(withoutFolder(["~/a"], 0)).toEqual([]);
  });

  it("turns adding off at the limit, with the reason", () => {
    expect(limitReason(7, 8)).toBeNull();
    expect(limitReason(8, 8)).toBe("A room can have at most 8 folders.");
  });

  it("says where programs run, and that file paths start with the folder name even for one folder", () => {
    expect(foldersNote(0)).toContain("Add a folder");
    for (const count of [1, 2]) {
      expect(foldersNote(count)).toBe("Programs run in the first folder unless an agent says otherwise. Agents write file paths as folder-name/path.");
    }
  });
});
