<div align="center">
  <h1>STS Automation Suite</h1>
  <h3>
    <span style="background: linear-gradient(45deg, #FF6B6B, #4ECDC4); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
      A BBF Labs Initiative
    </span>
  </h3>
  <p><em>Think • Build • Deploy</em></p>

  [![MIT License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
  [![Contributions Welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg?style=flat)](CONTRIBUTING.md)
</div>

## 🚀 Overview

Streamline your academic tasks with our comprehensive automation suite. This tool helps you efficiently manage course evaluations, exam check-ins, and DCIT surveys - saving you valuable time while ensuring accurate submissions.

## 🎯 Features

- **Course Evaluation Automation** - Evaluate multiple courses efficiently
- **Automated Exam Check-ins** - Seamlessly register for all your exams
- **DCIT Survey Automation** - Quick and accurate survey completion
- **Smart Response Generation** - Thoughtful, varied feedback for evaluations
- **Git Contributor Rewriter** - Erase, normalize, or replace contributor identities in git history, and fill missing GitHub contribution days

## 📋 Quick Start Guides

### Course Evaluation Automation

1. Copy the code from `sts.js`
2. Navigate to STS and select your course
3. **Important:** Select the lecturer to evaluate
4. Open developer tools (F12) and switch to console
5. Enable pasting:
   ```
   allow pasting
   ```
6. Paste the code and press Enter

### Exam Check-in Automation

⚠️ **Prerequisites:** Ensure all course evaluations are completed first

1. Open developer tools console (F12)
2. Enable pasting:
   ```
   allow pasting
   ```
3. Copy and paste code from `checkInToAllExams.js`
4. Execute the script

### DCIT Survey Automation

⚠️ **Prerequisites:** Select your student type and group number first

1. Open developer tools console (F12)
2. Enable pasting:
   ```
   allow pasting
   ```
3. Copy and paste code from `surveyAutomation.js`
4. Follow the prompts to enter:
   - Team member IDs (yours last)
   - Score allocation preferences

### Git Contributor Rewriter

`git_rewrite_contributors.py` is an interactive TUI for rewriting git history — removing contributors, merging duplicate identities, or filling missing GitHub contribution days with backdated commits.

#### Prerequisites

```bash
pip install rich questionary requests git-filter-repo
```

> **Windows:** ensure your Python `Scripts/` folder is on `PATH` so `git-filter-repo` is discoverable.

#### Usage

```bash
python git_rewrite_contributors.py                    # fully interactive
python git_rewrite_contributors.py <path/to/repo>     # skip repo path prompt
python git_rewrite_contributors.py --replace-zero-with-me   # replace trailer-only contributors with your identity
python git_rewrite_contributors.py --normalize-me            # consolidate your own duplicate aliases
python git_rewrite_contributors.py --fill-streaks            # fill missing GitHub contribution days
```

#### What each action does

| Action | Description |
|--------|-------------|
| **Erase contributor** | Drops commits where the target is sole author/committer; strips their identity from co-authored commits and all `*-by` trailers |
| **Normalize to my identity** | Rewrites a selected contributor's author, committer, and trailer entries to match your own identity |
| **Replace zero-commit authors** | Finds contributors who only appear in `Co-authored-by` trailers (no direct commits) and replaces them with you |
| **Consolidate my duplicates** | Detects aliases of your own identity across history and normalizes everything to one name/email |
| **Fill contribution streaks** | Reads your GitHub contribution calendar via the GraphQL API, identifies missing days, and creates backdated empty commits to fill gaps |

#### Fill streaks setup

The `--fill-streaks` action requires a GitHub personal access token with the `read:user` scope. You will be prompted for it interactively — it is never stored.

#### ⚠️ Warning

All history-rewrite operations are **destructive and irreversible**. After running, verify with `git log --all --oneline` then force-push:

```bash
git push --force --all
git push --force --tags
```

All collaborators will need to re-clone after a force-push.

#### 📜 Disclaimer

This tool is provided for legitimate use cases such as correcting mistaken identities, removing accidentally committed personal data, or consolidating your own duplicate profiles.

**Misuse of this tool may have consequences:**
- **Erasing contributors** from a shared or open-source project removes their attribution, which may violate open-source licenses (MIT, GPL, etc.) that require preservation of copyright notices.
- **Backdating commits** to artificially inflate a GitHub contribution graph is deceptive if used to misrepresent your activity to employers, academic institutions, or on a resume.
- **Force-pushing rewritten history** to a shared repository without team consent can destroy collaborators' work.

The authors of this project accept no liability for misuse. Use responsibly and only on repositories you own or have explicit permission to rewrite.

---

## 🤝 Contributing

We believe in the power of community collaboration! Your contributions can help make this tool even better.

### Our Amazing Contributors

<table>
  <tr>
    <td align="center">
      <a href="https://github.com/theniitettey">
        <img src="https://github.com/theniitettey.png" width="100px;" alt="Michael Perry Jr." style="border-radius:50%"/><br />
        <sub><b>Michael Perry</b></sub>
      </a>
    </td>
    <td align="center">
      <a href="https://github.com/bundana">
        <img src="https://github.com/bundana.png" width="100px;" alt="Bundana" style="border-radius:50%"/><br />
        <sub><b>Bundana</b></sub>
      </a>
    </td>
    <td align="center">
      <a href="https://github.com/donkorBN">
        <img src="https://github.com/donkorBN.png" width="100px;" alt="Donkor" style="border-radius:50%"/><br />
        <sub><b>Donkor</b></sub>
      </a>
    </td>
  </tr>
</table>

### How to Contribute

We welcome all contributions, big or small! Here's how to get started:

1. 🍴 Fork the repository
2. 🌿 Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. 💻 Make your changes
4. 📝 Commit with clear messages (`git commit -m 'Add: Amazing Feature'`)
5. 🚀 Push to your branch (`git push origin feature/AmazingFeature`)
6. 🔄 Open a Pull Request

For major changes, please open an issue first to discuss what you'd like to change.

## ⚠️ Important Notes

- Review generated responses before submission
- Use responsibly and in accordance with institutional policies
- Report issues or suggest improvements via GitHub issues

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

<div align="center">
  <h3>🎉 Ready to Automate?</h3>
  <p>Start saving time and reducing manual work today!</p>
  
  [![Get Started](https://img.shields.io/badge/Get%20Started-4ECDC4?style=for-the-badge)](docs/getting-started.md)
</div>
