import { spawn } from 'child_process';
import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { resolve } from 'path';

export const POST: RequestHandler = async ({ request }) => {
	const { agents = 50, rounds = 10 } = await request.json();

	// Path to the Python simulation
	const simDir = resolve(process.cwd(), '..', 'sim');
	const pythonPath = resolve(simDir, '.venv', 'bin', 'python');

	const child = spawn(pythonPath, ['-m', 'sim.engine'], {
		cwd: simDir,
		env: {
			...process.env,
			MERIDIAN_AGENTS: String(agents),
			MERIDIAN_ROUNDS: String(rounds),
		},
	});

	const stream = new ReadableStream({
		start(controller) {
			child.stdout.on('data', (data: Buffer) => {
				controller.enqueue(data);
			});

			child.stderr.on('data', (data: Buffer) => {
				console.error('[sim stderr]', data.toString());
			});

			child.on('close', () => {
				controller.close();
			});

			child.on('error', (err) => {
				console.error('[sim error]', err);
				controller.close();
			});
		},
		cancel() {
			child.kill();
		},
	});

	return new Response(stream, {
		headers: {
			'Content-Type': 'application/x-ndjson',
			'Transfer-Encoding': 'chunked',
		},
	});
};
