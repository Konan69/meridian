import { json } from '@sveltejs/kit';

const ENDPOINTS = {
	engine: 'http://localhost:4080',
	atxp: 'http://localhost:3010',
	cdp: 'http://localhost:3030',
	stripe: 'http://localhost:3020',
	ap2: 'http://localhost:3040'
} as const;

async function fetchJson(url: string): Promise<unknown | null> {
	try {
		const response = await fetch(url);
		if (!response.ok) return null;
		return await response.json();
	} catch {
		return null;
	}
}

async function fetchEngineHealth() {
	try {
		const response = await fetch(`${ENDPOINTS.engine}/health`);
		if (!response.ok) return null;
		const text = await response.text();
		return {
			status: text.trim() || 'ok',
			service: 'meridian-engine'
		};
	} catch {
		return null;
	}
}

export async function GET({ url }: { url: URL }) {
	const mode = url.searchParams.get('mode');
	const atxpQuery = mode ? `?mode=${encodeURIComponent(mode)}` : '';
	const [capabilities, atxpFunding, engineHealth, atxpHealth, cdpHealth, stripeHealth, ap2Health] =
		await Promise.all([
			fetchJson(`${ENDPOINTS.engine}/capabilities`),
			fetchJson(`${ENDPOINTS.atxp}/funding${atxpQuery}`),
			fetchEngineHealth(),
			fetchJson(`${ENDPOINTS.atxp}/health${atxpQuery}`),
			fetchJson(`${ENDPOINTS.cdp}/health`),
			fetchJson(`${ENDPOINTS.stripe}/health`),
			fetchJson(`${ENDPOINTS.ap2}/health`)
		]);

	return json({
		engineCaps: capabilities,
		atxpFunding,
		health: {
			engine: engineHealth,
			atxp: atxpHealth,
			cdp: cdpHealth,
			stripe: stripeHealth,
			ap2: ap2Health
		}
	});
}
