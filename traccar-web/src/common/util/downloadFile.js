/**
 * Save a file that needs the signed-in session to fetch.
 *
 * A plain link cannot be used for these. When the app is installed to the home
 * screen or running inside the Android wrapper, tapping a link hands the URL to
 * the system's download handler, which makes its own request without the
 * session cookie, gets a 401 and fails silently - nothing downloads and nothing
 * is said. Fetching here, where the cookie exists, and handing over the bytes
 * avoids that entirely.
 *
 * Returns nothing and throws with a readable message, so callers can show it.
 */
export default async (url, filename) => {
  const response = await fetch(url, { credentials: 'include' });
  if (!response.ok) {
    let detail;
    try {
      detail = (await response.json())?.detail;
    } catch {
      detail = null;
    }
    throw new Error(
      typeof detail === 'string' ? detail : `That file could not be fetched (${response.status}).`,
    );
  }

  const blob = await response.blob();
  const href = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = href;
  link.download = filename;
  // Firefox needs the link in the document before it will follow the click.
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Give the browser a moment to start the save before the blob is let go.
  window.setTimeout(() => window.URL.revokeObjectURL(href), 10000);
};
