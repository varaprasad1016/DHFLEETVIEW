/**
 * Ask the server for a report as a PDF and let the browser save it.
 *
 * This deliberately does not fetch the file into a blob and save that. A blob
 * download works on a desktop browser and fails on a phone: inside an Android
 * WebView a `blob:` URL arrives at the download manager with no name and no
 * type, and the report lands in Downloads as a `.bin` nobody can open by
 * double-clicking. Navigating to the real URL instead hands the job to the
 * browser, which reads the filename and the content type off the response the
 * way it was designed to - the server already sends
 * `Content-Disposition: attachment; filename="PJ19FBK-trips-20261020.pdf"`.
 *
 * The cost is that a failure arrives as the server's JSON rather than a toast,
 * which is a fair trade for a file that saves correctly everywhere.
 */
export const reportPdfUrl = (kind, { deviceIds = [], from, to }) => {
  const query = new URLSearchParams({ kind, from, to });
  deviceIds.forEach((id) => query.append('deviceId', id));
  return `/tacho/api/reports/pdf?${query.toString()}`;
};

export const downloadReportPdf = async (kind, filter) => {
  const link = document.createElement('a');
  link.href = reportPdfUrl(kind, filter);
  // Same origin, so this is honoured; the server's own filename wins where the
  // browser reads one, and this is the fallback for those that do not.
  link.download = '';
  link.rel = 'noopener';
  document.body.appendChild(link);
  link.click();
  link.remove();
};

export default downloadReportPdf;
