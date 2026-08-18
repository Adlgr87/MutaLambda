# MutaLambda VS Code Extension

## Features

- Real-time optimization suggestions while coding
- Inline code actions for quick fixes
- Hover tooltips with performance metrics
- Integration with MutaLambda LSP server

## Installation

1. Open VS Code
2. Install from Marketplace or use:
   ```bash
   code --install-extension mutalambda.mutalambda
   ```

## Configuration

Add to `.vscode/settings.json`:

```json
{
  "mutalambda.enabled": true,
  "mutalambda.mode": "fast",
  "mutalambda.llm.provider": "ollama",
  "mutalambda.showExplanations": true
}
```

## Commands

- `MutaLambda: Optimize Function` - Analyze and optimize current function
- `MutaLambda: Explain Optimization` - Show detailed explanation
- `MutaLambda: Analyze Project` - Run full project analysis

## Supported Languages

- Python (.py)
- Go (.go)
- Rust (.rs)
- C/C++ (.cpp, .c, .h, .hpp)
