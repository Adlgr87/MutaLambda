module.exports = function(context) {
    const { languages, workspace, window, ExtensionContext } = require('vscode');
    const { LanguageClient, TransportKind } = require('vscode-languageclient/node');

    let client;

    context.subscriptions.push(
        languages.registerCodeActionsProvider(
            ['python', 'go', 'rust', 'cpp'],
            {
                provideCodeActions(document, range, context, token) {
                    const actions = [];
                    
                    // Add optimization suggestion
                    actions.push({
                        title: 'MutaLambda: Optimize this function',
                        kind: 'quickfix',
                        edit: new workspace.WorkspaceEdit()
                    });
                    
                    // Add explain option
                    actions.push({
                        title: 'MutaLambda: Explain optimization',
                        kind: 'refactor',
                        command: 'mutalambda.explain',
                        arguments: [document.uri]
                    });
                    
                    return actions;
                }
            },
            {
                provideCodeActions: true
            }
        ),
        
        languages.registerHoverProvider(
            ['python', 'go', 'rust', 'cpp'],
            {
                provideHover(document, position, token) {
                    // Show optimization metrics
                    return {
                        contents: [
                            '```MutaLambda\n',
                            'Optimization Potential: Medium\n',
                            'Estimated Speedup: 1.2x\n',
                            'Risk Level: Low\n',
                            '```\n'
                        ]
                    };
                }
            }
        ),
        
        workspace.onDidChangeTextDocument(async (event) => {
            if (client && client.isRunning()) {
                // Send document changes to LSP server
                await client.sendNotification('textDocument/didChange', {
                    textDocument: {
                        uri: event.document.uri.toString(),
                        version: event.document.version
                    },
                    contentChanges: event.contentChanges
                });
            }
        }),
        
        workspace.onDidSaveTextDocument(async (document) => {
            if (client && client.isRunning()) {
                await client.sendNotification('textDocument/didSave', {
                    textDocument: {
                        uri: document.uri.toString()
                    },
                    text: document.getText()
                });
            }
        })
    );

    function startClient(context) {
        const serverModule = context.asAbsolutePath(require.resolve('./server.js'));
        
        const serverOptions = {
            run: { module: serverModule, transport: TransportKind.ipc },
            debug: { module: serverModule, transport: TransportKind.ipc }
        };
        
        const clientOptions = {
            documentSelector: [
                { scheme: 'file', language: 'python' },
                { scheme: 'file', language: 'go' },
                { scheme: 'file', language: 'rust' },
                { scheme: 'file', language: 'cpp' }
            ],
            synchronize: {
                configurationSection: ['mutalambda']
            }
        };
        
        client = new LanguageClient(
            'mutalambda',
            'MutaLambda Optimization Server',
            serverOptions,
            clientOptions
        );
        
        return client.start();
    }

    return {
        activate: (ctx) => {
            context.subscriptions.push(...[
                ...startClient(ctx).then(() => []).catch(err => {
                    window.showErrorMessage(`MutaLambda failed to start: ${err}`);
                })
            ]);
        },
        deactivate: () => {
            if (client) {
                client.stop();
            }
        }
    };
};
