# Source Management

This project uses a feature-branch workflow to keep `main` stable and auditable.

## Required Workflow

When a commit and push is requested:

1. Inspect the worktree and current branch.
2. Create a feature branch from `main` before committing.
3. Commit the scoped changes on the feature branch.
4. Push the feature branch to `origin`.
5. Report the branch name, commit, and validation results.
6. Wait for explicit approval before merging to `main`.
7. Merge to `main` only after approval, preferably through a pull request.

Recommended branch names:

```text
codex/<short-task-name>
feature/<short-task-name>
fix/<short-task-name>
```

If uncommitted changes already exist while on `main`, create the feature branch
first. `git switch -c codex/<short-task-name>` keeps the working tree changes
and moves the eventual commit off `main`.

Direct pushes to `main` are prohibited for normal development.

## Recommended Local Commands

Start a new branch:

```bash
git switch main
git pull --ff-only
git switch -c codex/<short-task-name>
```

Commit and push the feature branch:

```bash
git status --short
git add <changed-files>
git commit -m "<short change summary>"
git push -u origin codex/<short-task-name>
```

After approval, merge through GitHub or merge locally:

```bash
git switch main
git pull --ff-only
git merge --ff-only codex/<short-task-name>
git push origin main
```

If fast-forward merge is not possible, use a pull request or rebase the feature
branch after confirming with the project owner.

## Protecting `main` On GitHub

The actual prevention of direct pushes must be enforced on the remote repository
host. A local Git setting or hook can help prevent mistakes on one machine, but
it does not protect the shared repository.

Recommended GitHub branch protection:

1. Open the repository on GitHub.
2. Go to `Settings` -> `Branches`.
3. Add a branch protection rule for `main`.
4. Enable `Require a pull request before merging`.
5. Enable at least one approval if more than one maintainer is available.
6. Enable `Require status checks to pass before merging` once CI checks exist.
7. Enable `Require conversation resolution before merging`.
8. Enable `Do not allow bypassing the above settings` if administrators should
   follow the same policy.
9. Keep force pushes and deletions disabled.

For newer or organization-managed repositories, GitHub rulesets can be used
instead of, or alongside, branch protection. Create a branch ruleset targeting
`main`, set enforcement to active, require pull requests, and avoid adding bypass
actors unless there is a documented release process.

Do not use `Lock branch` for normal development. It makes the branch read-only
and is better suited to temporary release freezes than to ordinary pull-request
based development.

## Optional Local Guard

A local `pre-push` hook can warn against accidental direct pushes to `main`, but
it is only advisory because it lives in one clone. Remote branch protection is
still required.
