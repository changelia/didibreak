# Limitations

What didibreak cannot check, shared and per language.

## Git

- **Base version:** the working tree (committed, staged, unstaged and
  untracked files) is compared with one base commit (`--base`, default
  `HEAD`). A repository without any commit has no base and is an error.
- **Submodules:** changes inside git submodules are not checked; git reports
  a changed submodule only as its folder.
- **Shallow clones:** a base older than the cloned history cannot be found;
  fetch more history first (`git fetch --unshallow`).
- **Renames:** a rename is recognised when git can see it, for example after
  `git mv` or a commit. A file that was moved but not yet added to git is
  treated as a deleted file plus a new file.
- **Deleted files:** functions in deleted files are not checked.

The rest of this page is written together with the analysis features.
