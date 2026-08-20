# MutaLambda Neovim Plugin

## Installation

### Using packer.nvim
```lua
use {
  'Adlgr87/MutaLambda',
  requires = {{ 'neovim/nvim-lspconfig' }}
}
```

### Using lazy.nvim
```lua
{
  'Adlgr87/MutaLambda',
  dependencies = { 'neovim/nvim-lspconfig' },
  config = function()
    require('mutalambda').setup()
  end
}
```

## Configuration

```lua
require('mutalambda').setup({
  enabled = true,
  mode = 'fast',  -- 'fast' or 'deep'
  llm = {
    provider = 'ollama',  -- 'ollama', 'openai', 'anthropic'
    model = 'llama3',
  },
  show_explanations = true,
})
```

## Commands

- `:MutaLambdaOptimize` - Optimize current function
- `:MutaLambdaExplain` - Show explanation for last optimization
- `:MutaLambdaAnalyze` - Analyze entire project

## Keymaps

```lua
-- Optimize function under cursor
vim.keymap.set('n', '<leader>mo', ':MutaLambdaOptimize<CR>')

-- Show explanation
vim.keymap.set('n', '<leader>me', ':MutaLambdaExplain<CR>')

-- Analyze project
vim.keymap.set('n', '<leader>ma', ':MutaLambdaAnalyze<CR>')
```

## Features

- Automatic diagnostics on save
- Inline code actions
- Performance hover information
- Buffer-aware analysis

## Supported Languages

- Python
- Go
- Rust
- C/C++
