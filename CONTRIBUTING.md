# Contributing and Development

We welcome contributions! To contribute to this repository, please follow these steps:

## Code and Testing

- **Code Style and Structure:**

- **Pre-Commit Hooks:** Install pre-commit hooks in this repository using the `pre-commit install` command.

- **Readable Code Structure:** Structure your code in a readable manner. The main logic should be in the default rule function, with implementation details in helper functions. Avoid nested `if` statements and unnecessary `else` statements to maintain code clarity and simplicity.

- **Remove Debug Statements:** Remove any development debug statements from your files.

- **Automated Tests:** We aim for full test coverage, so **partial tests will not be accepted**. The tests should cover all typical usage scenarios as well as edge cases to ensure robustness.

- **Testing Tool:** It is recommended to run `pytest` frequently during development to ensure that all aspects of your code are functioning as expected.

## Documentation and Maintenance

- **Changelog:** `CHANGELOG.md` is generated automatically by `commitizen` from commit messages. Not need to update `CHANGELOG.md` manually. Focus on informative and clear commit messages which end in the release notes.

- **Documentation:** Regularly check and update the documentation to keep it current.

- **PR/MR Descriptions and Documentation:** When making contributions, clearly describe any changes or new features in both the PR (Pull Request on GitHub) or MR (Merge Request on GitLab) description and the project documentation. If you're modifying the output style, please include a thumbnail of the new style.

## Development and Local Testing

1. **Clone the Project**

- Clone the repository to your local machine using:

```sh
git clone <project_clone_url>
```

2. **Set Up Development Environment:**

- Create and activate a virtual environment:

  ```sh
  python -m venv venv && source ./venv/bin/activate
  ```

  or:

  ```sh
  virtualenv venv && source ./venv/bin/activate
  ```

- Install the project and development dependencies:
  ```sh
  pip install -e '.[dev]'
  ```

3. **Testing Your Changes:**

- Before submitting a pull request, ensure your changes pass all the tests. You can run the test suite with the following command:

  ```sh
  pytest
  ```

## Releasing

Maintainers release with `commitizen`. Creating a **GitHub Release** triggers the PyPI publish workflow (`.github/workflows/pypi-publish.yml`).

1. **Bump version** (creates a bump commit, updates `CHANGELOG.md`, and creates a local annotated tag such as `v0.6.0`):

   ```sh
   git checkout -b bump/new_version
   cz bump --get-next   # preview next version from conventional commits
   cz bump              # apply that bump when the preview looks correct
   ```

   If the next version is not what you expect, force the increment instead:

   ```sh
   cz bump --increment=MINOR   # or MAJOR / PATCH
   ```
2. **Open and merge the bump MR** on GitLab, then ensure `main` is up to date locally.

3. **Push the tag** (created by `cz bump`; push after the bump commit is on `main`):

   ```sh
   git push origin vX.Y.Z
   ```

   If GitHub is a separate remote (mirror of this GitLab repo), also push the tag there so the release can reference it:

   ```sh
   git push github vX.Y.Z
   ```

4. **Create the GitHub Release** from that tag (this starts the PyPI publish job):

   ```sh
   gh release create vX.Y.Z --title "vX.Y.Z" --generate-notes --repo ydhub/esp-test-utils
   ```

   Or use the GitHub UI: **Releases → Draft a new release → choose tag `vX.Y.Z` → Publish release**.
   Prefer pasting the matching section from `CHANGELOG.md` into the release notes when you want curated notes.

---

👏**Thank you for your contributions.**
