# Template Python Package

**Welcome to the Template Python Package!** This repository serves as a starting template for Python projects within our organization.

**Please adapt this README.md document to describe your specific project. You can omit parts of this template or add additional information as needed to best fit your project.**

---

- [Template Python Package](#template-python-package)
  - [Getting Started](#getting-started)
    - [Sample Project Setup Procedure](#sample-project-setup-procedure)
    - [Adapting the Project](#adapting-the-project)
  - [Tools and project settings](#tools-and-project-settings)
    - [Build System](#build-system)
    - [Standard Project Code Quality Tools](#standard-project-code-quality-tools)
    - [Linting Local Code with Pre-Commit Hooks](#linting-local-code-with-pre-commit-hooks)
  - [Documentation](#documentation)
    - [CHANGELOG](#changelog)
  - [Licensing](#licensing)
  - [Contributing Guide](#contributing-guide)
  - [Contributing](#contributing)

---

## Getting Started

### Sample Project Setup Procedure

1. Clone this project.
2. Create and activate a virtual environment. In Python projects, you should **always use virtual environments** (`virtualenv`/`venv`) to prevent affecting your system Python installation by installing project-specific dependencies.
3. If you see pip related warnings, ensure your `pip` is up-to-date by running `pip install --upgrade pip`. This project requires a recent version of `pip` to correctly handle dependencies and installation.
4. Install development tools using `pip install -e '.[dev]'`.
5. Install pre-commit hooks with `pre-commit install`.
6. Explore the sample app located in `template_package` and its corresponding tests in `tests`.
7. Run the sample app with the command `mooo`.

   ```
   (venv) $ mooo
    _____________
   | Template Package |
    =============
              \
                \
                  ^__^
                  (oo)\_______
                  (__)\       )\/\
                      ||----w |
                      ||     ||
   ```

8. Run codebase tests using `pytest`.

### Adapting the Project

Replace the sample app and tests with your own application, following the provided directory structure.

---

## Tools and project settings

### Build System

- There's no longer a need to use Poetry or Pipenv; this sample project adopts a modern approach using `setuptools` along with a `pyproject.toml` configuration file.
- The `pyproject.toml` file encompasses not just the project configuration but also the settings for all helper tools, including `mypy`, `pylint`, `pytest`, `commitizen`, `ruff`, etc.
- This centralizes all project configurations in one easily maintainable location.
- `pyproject.toml` also facilitates the grouping of dependencies based on their usage. This allows for a clear distinction between production dependencies, development dependencies, those specific to CI testing and so on.

---

### Standard Project Code Quality Tools

The following tools are pre-configured in `pyproject.toml` according to the standard defaults for Espressif projects. While you can adapt the configuration to fit your specific needs, it is recommended to rely on these standard settings. This approach helps maintain consistency in code structure and settings across company projects.

- **Codespell**: Identifies and corrects common misspellings in Python files.
- **Commitizen**: Assists in automatically creating changelogs (`cz bump`) and helps format valid commit messages (`cz commit`).
- **Mypy**: Provides type checking for Python code.
- **Pylint**: Ensures code quality and adherence to best practices.
- **Pytest**: Used for testing the codebase and displaying code coverage.
- **Ruff formatter**: Automatically formats Python code for consistent styling. Fully backwards compatible with `black`, but faster.
- **Ruff linter**: A faster and lightweight alternative to `flake8`.

### Linting Local Code with Pre-Commit Hooks

In this project, we utilize pre-commit hooks to streamline the use of linting tools such as `ruff`, `mypy`, and `pylint`. This method simplifies the setup process and ensures consistency across development environments.

- **Centralized Configuration**: Linter settings are defined in one location within the `.pre-commit-config.yaml` file, making it easier to maintain and update the configurations.
- **Isolated Environments**: Running linters through pre-commit hooks provides isolated environments for each tool, enhancing safety and reducing conflicts between project dependencies.
- **Ease of Use**: Developers can run linters **without the need to manage individual tool installations as project development dependencies**.

To utilize these tools, simply follow these commands:

| Tool               | Command                         |
| ------------------ | ------------------------------- |
| **Codespell**      | `pre-commit run -a codespell`   |
| **Mypy**           | `pre-commit run -a mypy`        |
| **Pylint**         | `pre-commit run -a pylint`      |
| **Ruff formatter** | `pre-commit run -a ruff-format` |
| **Ruff linter**    | `pre-commit run -a ruff`        |

**Note**: The `-a` flag runs the specified tool against all files in your project. If you wish to run it only on changed files in the git working tree (similar to how `pre-commit` operates during commit), you can stage them and execute `pre-commit`. This runs all pre-commit hooks in the same manner as a `git commit`, detecting and fixing code style issues.

**Maintaining Hooks**: Regularly update your pre-commit hooks configuration with `pre-commit autoupdate` to ensure alignment with the latest tool versions and project standards. As a best practice, after running `pre-commit autoupdate`, execute `pre-commit run --all-files` to verify that the updates do not introduce issues. This step should be done before pushing the updated `.pre-commit-config.yaml` file with the hooks new versions to the repository.

---

## Documentation

Good documentation is essential for any project. It helps users understand what the project is about, how to configure custom parameters, and any possible limitations of the project.

A comprehensive Contributing Guide should also be included, providing clear instructions for potential contributors on setting up the development environment and the proper procedures for contributing to the project. This ensures a smooth review and acceptance process.

### CHANGELOG

- The `CHANGELOG.md` file is automatically created and updated by the `commitizen` tool using the `cz bump` command.
- The recommended process for updating the `CHANGELOG.md` includes:
  - Creating a branch, e.g., `bump/version-1.5.0`.
  - Running `cz bump`, which updates the `CHANGELOG.md` and creates a tagged commit.
  - Pushing changes to the MR branch.
  - Reviewing changes in the GitLab UI and merging the MR.
  - Creating a release using the appropriate tag and copying release notes from the `CHANGELOG.md`.

## Licensing

- The default license for Espressif projects is `Apache 2.0`.
- While you can choose a different license type, it's important to understand the differences between various open-source licenses before making this decision.

## Contributing Guide

- Provides guidelines for contributors, including coding standards and project-specific practices.
- This document should detail how to set up the project's development environment on a local machine.
- It should also outline the requirements for accepting MRs/PRs, including the testing process, test coverage, and other relevant criteria.

---

## Contributing

📘 If you are interested in contributing to this project, see the [project Contributing Guide](CONTRIBUTING.md).
