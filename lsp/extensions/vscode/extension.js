// MutaLambda VS Code extension entry point.
//
// Previous versions of this file exported a bare function instead of the
// `activate` / `deactivate` pair VS Code requires, pointed `package.json`
// at a `dist/` build that no sources produced, and tried to resolve the
// language server as a Node module that does not exist. The server is the
// Python module `lsp/server.py`, launched below with the configured
// interpreter over stdio.

const path = require('path');
const { commands, window, workspace } = require('vscode');
const { LanguageClient, TransportKind } = require('vscode-languageclient/node');

const DOCUMENT_SELECTOR = [
    { scheme: 'file', language: 'python' },
    { scheme: 'file', language: 'go' },
    { scheme: 'file', language: 'rust' },
    { scheme: 'file', language: 'cpp' },
    { scheme: 'file', language: 'c' },
];

/** @type {LanguageClient | undefined} */
let client;

/**
 * Resolve the Python LSP server entry point.
 *
 * Repo layout: <ext>/lsp/extensions/vscode/extension.js -> <repo>/lsp/server.py
 */
function resolveServerScript(context) {
    const configured = workspace.getConfiguration('mutalambda').get('server.path');
    if (configured) {
        return configured;
    }
    return context.asAbsolutePath(path.join('..', '..', 'server.py'));
}

function buildServerOptions(context) {
    const interpreter =
        workspace.getConfiguration('mutalambda').get('python.interpreter') || 'python3';
    const script = resolveServerScript(context);
    const run = {
        command: interpreter,
        args: [script],
        transport: TransportKind.stdio,
    };
    return { run, debug: run };
}

async function startClient(context) {
    const clientOptions = {
        documentSelector: DOCUMENT_SELECTOR,
        synchronize: {
            configurationSection: 'mutalambda',
        },
    };

    client = new LanguageClient(
        'mutalambda',
        'MutaLambda Optimization Server',
        buildServerOptions(context),
        clientOptions
    );

    await client.start();
    return client;
}

function registerCommands(context) {
    // Every command declared under `contributes.commands` in package.json must
    // be registered here, otherwise VS Code reports "command not found".
    const handlers = {
        'mutalambda.optimize': async () => {
            const editor = window.activeTextEditor;
            if (!editor) {
                window.showWarningMessage('MutaLambda: open a file to optimize first.');
                return;
            }
            if (!client || !client.isRunning()) {
                window.showWarningMessage('MutaLambda: language server is not running.');
                return;
            }
            await client.sendNotification('textDocument/didSave', {
                textDocument: { uri: editor.document.uri.toString() },
                text: editor.document.getText(),
            });
            window.showInformationMessage('MutaLambda: analysis requested.');
        },
        'mutalambda.explain': async () => {
            const editor = window.activeTextEditor;
            if (!editor || !client || !client.isRunning()) {
                window.showWarningMessage('MutaLambda: nothing to explain yet.');
                return;
            }
            const result = await client.sendRequest('textDocument/hover', {
                textDocument: { uri: editor.document.uri.toString() },
                position: { line: editor.selection.active.line, character: 0 },
            });
            const value = result && result.contents ? result.contents.value : null;
            window.showInformationMessage(value || 'MutaLambda: no explanation available.');
        },
        'mutalambda.analyzeProject': async () => {
            const folders = workspace.workspaceFolders;
            if (!folders || folders.length === 0) {
                window.showWarningMessage('MutaLambda: open a folder to analyze a project.');
                return;
            }
            window.showInformationMessage(
                `MutaLambda: project analysis runs via the CLI — ` +
                    `\`mutalambda recommend ${folders[0].uri.fsPath}\`.`
            );
        },
    };

    for (const [id, handler] of Object.entries(handlers)) {
        context.subscriptions.push(commands.registerCommand(id, handler));
    }
}

async function activate(context) {
    registerCommands(context);

    if (workspace.getConfiguration('mutalambda').get('enabled') === false) {
        return;
    }

    try {
        await startClient(context);
    } catch (err) {
        window.showErrorMessage(`MutaLambda failed to start: ${err}`);
    }
}

function deactivate() {
    if (!client) {
        return undefined;
    }
    return client.stop();
}

module.exports = { activate, deactivate };
