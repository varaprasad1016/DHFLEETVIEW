import { makeStyles } from 'tss-react/mui';

export default makeStyles()((theme) => ({
  container: {
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
    // Printing has no viewport for a height of 100% to mean anything, and a
    // scrollbox prints only the slice on screen - which is why Save as PDF
    // came out blank. Let the content flow onto pages instead.
    '@media print': {
      height: 'auto',
      display: 'block',
      overflow: 'visible',
    },
  },
  containerMap: {
    flexBasis: 'var(--report-map-height, 40%)',
    flexShrink: 0,
    // A live map prints as a grey rectangle at best.
    '@media print': {
      display: 'none',
    },
  },
  containerMain: {
    overflow: 'auto',
    '@media print': {
      overflow: 'visible',
      height: 'auto',
    },
  },
  header: {
    position: 'sticky',
    left: 0,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'stretch',
  },
  columnAction: {
    width: '1%',
    paddingLeft: theme.spacing(1),
    '@media print': {
      display: 'none',
    },
  },
  columnActionContainer: {
    display: 'flex',
  },
  filter: {
    display: 'inline-flex',
    flexWrap: 'wrap',
    gap: theme.spacing(2),
    padding: theme.spacing(3, 2, 2),
    '@media print': {
      display: 'none !important',
    },
  },
  filterItem: {
    minWidth: 0,
    flex: `1 1 ${theme.dimensions.filterFormWidth}`,
  },
  filterButtons: {
    display: 'flex',
    gap: theme.spacing(1),
    flex: `1 1 ${theme.dimensions.filterFormWidth}`,
  },
  filterButton: {
    flexGrow: 1,
  },
  chart: {
    flexGrow: 1,
    overflow: 'hidden',
  },
  actionCellPadding: {
    '&.MuiTableCell-body': {
      paddingTop: 0,
      paddingBottom: 0,
    },
    '@media print': {
      display: 'none',
    },
  },
}));
