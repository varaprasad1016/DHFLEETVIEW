import { saveAs } from 'file-saver';

const borderDefinition = {
  top: { style: 'thin' },
  left: { style: 'thin' },
  bottom: { style: 'thin' },
  right: { style: 'thin' },
};

let companyNamePromise;

const getCompanyName = async () => {
  if (!companyNamePromise) {
    companyNamePromise = fetch('/api/tachograph/company')
      .then((response) => (response.ok ? response.json() : {}))
      .then((data) => data.name || 'DH FleetView')
      .catch(() => 'DH FleetView');
  }
  return companyNamePromise;
};

const normaliseRows = (sheets) => Array.from(sheets.entries())
  .filter(([, rows]) => rows && rows.length)
  .map(([sheetTitle, rows]) => ({
    sheetTitle,
    headers: Object.keys(rows[0]),
    rows,
  }));

const textValue = (value) => {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/<[^>]+>/g, '')
    .replace(/\s+/g, ' ')
    .trim();
};

const pdfText = (value) => textValue(value)
  .replace(/[^\x20-\x7E]/g, '?')
  .replace(/\\/g, '\\\\')
  .replace(/\(/g, '\\(')
  .replace(/\)/g, '\\)');

const createPdf = (title, company, sheets) => {
  const lines = [`${company}`, title, ''];
  normaliseRows(sheets).forEach(({ sheetTitle, headers, rows }) => {
    lines.push(`[${sheetTitle}]`);
    lines.push(headers.join(' | '));
    rows.forEach((row) => {
      const line = headers.map((header) => textValue(row[header])).join(' | ');
      // Keep the PDF readable on phones and avoid overflowing the page width.
      for (let offset = 0; offset < Math.max(line.length, 1); offset += 105) {
        lines.push(line.slice(offset, offset + 105));
      }
    });
    lines.push('');
  });

  const linesPerPage = 52;
  const pageLines = [];
  for (let i = 0; i < lines.length; i += linesPerPage) {
    pageLines.push(lines.slice(i, i + linesPerPage));
  }
  if (!pageLines.length) pageLines.push([]);

  const objects = [];
  const addObject = (value) => {
    objects.push(value);
    return objects.length;
  };
  const fontId = addObject('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>');
  const pageIds = [];
  const contentIds = [];
  pageLines.forEach((page) => {
    const commands = ['BT', '/F1 10 Tf', '40 800 Td'];
    page.forEach((line, index) => {
      if (index === 0) commands.push('/F1 14 Tf');
      if (index === 1) commands.push('/F1 12 Tf');
      if (index === 2) commands.push('/F1 10 Tf');
      commands.push(`(${pdfText(line)}) Tj`, '0 -14 Td');
    });
    commands.push('ET');
    const content = commands.join('\n');
    const contentId = addObject(`<< /Length ${content.length} >>\nstream\n${content}\nendstream`);
    contentIds.push(contentId);
    pageIds.push(null);
  });
  const pagesId = addObject('');
  pageIds.forEach((_, index) => {
    pageIds[index] = addObject(
      `<< /Type /Page /Parent ${pagesId} 0 R /MediaBox [0 0 595 842] `
      + `/Resources << /Font << /F1 ${fontId} 0 R >> >> /Contents ${contentIds[index]} 0 R >>`,
    );
  });
  objects[pagesId - 1] = `<< /Type /Pages /Kids [${pageIds.map((id) => `${id} 0 R`).join(' ')}] /Count ${pageIds.length} >>`;
  const catalogId = addObject(`<< /Type /Catalog /Pages ${pagesId} 0 R >>`);

  let output = '%PDF-1.4\n';
  const offsets = [0];
  objects.forEach((object, index) => {
    offsets.push(output.length);
    output += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xrefOffset = output.length;
  output += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  offsets.slice(1).forEach((offset) => {
    output += `${String(offset).padStart(10, '0')} 00000 n \n`;
  });
  output += `trailer\n<< /Size ${objects.length + 1} /Root ${catalogId} 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`;
  return output;
};

const exportReport = async (title, fileName, sheets, theme, format = 'xlsx') => {
  if (sheets.size === 0) return;

  const company = await getCompanyName();
  if (format === 'pdf') {
    const blob = new Blob([createPdf(title, company, sheets)], { type: 'application/pdf' });
    saveAs(blob, fileName.replace(/\.xlsx$/i, '.pdf'));
    return;
  }

  const { default: ExcelJS } = await import('exceljs');
  const workbook = new ExcelJS.Workbook();
  const headerColor = `FF${theme.palette.primary.main.replace('#', '').toUpperCase()}`;

  sheets.forEach((rows, sheetTitle) => {
    if (!rows.length) return;
    const worksheet = workbook.addWorksheet(sheetTitle);
    const headers = Object.keys(rows[0]);

    const companyRow = worksheet.addRow([company]);
    if (headers.length > 1) worksheet.mergeCells(1, 1, 1, headers.length);
    companyRow.font = { bold: true };
    const titleRow = worksheet.addRow([title]);
    if (headers.length > 1) worksheet.mergeCells(2, 1, 2, headers.length);
    titleRow.font = { bold: true };

    const headerRow = worksheet.addRow(headers);
    headerRow.eachCell((cell) => {
      cell.border = borderDefinition;
      cell.font = {};
      cell.fill = {
        type: 'pattern',
        pattern: 'solid',
        fgColor: { argb: headerColor },
      };
    });

    rows.forEach((item) => {
      const row = worksheet.addRow(headers.map((header) => item[header]));
      row.eachCell({ includeEmpty: true }, (cell) => {
        cell.border = borderDefinition;
        cell.font = {};
      });
    });

    headers.forEach((header, index) => {
      let maxLength = String(header).length;
      rows.forEach((item) => {
        maxLength = Math.max(maxLength, textValue(item[header]).length);
      });
      worksheet.getColumn(index + 1).width = Math.max(maxLength + 2, 10);
    });
  });

  const blob = new Blob([await workbook.xlsx.writeBuffer()], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  saveAs(blob, fileName);
};

const exportExcel = (title, fileName, sheets, theme, format = 'xlsx') =>
  exportReport(title, fileName, sheets, theme, format);

export { exportReport };
export default exportExcel;
