import { alpha } from '@mui/material/styles';

const radius = 10;

export default {
  MuiUseMediaQuery: {
    defaultProps: {
      noSsr: true,
    },
  },
  MuiCssBaseline: {
    styleOverrides: {
      body: {
        WebkitFontSmoothing: 'antialiased',
        MozOsxFontSmoothing: 'grayscale',
        fontFeatureSettings: '"cv02", "cv03", "cv04", "cv11"',
      },
      '*::-webkit-scrollbar': {
        width: 8,
        height: 8,
      },
      '*::-webkit-scrollbar-thumb': {
        backgroundColor: 'rgba(102, 112, 133, 0.28)',
        borderRadius: 8,
        '&:hover': {
          backgroundColor: 'rgba(102, 112, 133, 0.5)',
        },
      },
      '*::-webkit-scrollbar-track': {
        backgroundColor: 'transparent',
      },
      '*::-webkit-scrollbar-corner': {
        backgroundColor: 'transparent',
      },
    },
  },
  MuiOutlinedInput: {
    styleOverrides: {
      root: ({ theme }) => ({
        backgroundColor: theme.palette.background.paper,
        borderRadius: radius,
        transition: theme.transitions.create(['border-color', 'box-shadow']),
        '& .MuiOutlinedInput-notchedOutline': {
          borderColor: theme.palette.divider,
          borderWidth: 1,
        },
        '&:hover .MuiOutlinedInput-notchedOutline': {
          borderColor: alpha(theme.palette.text.primary, 0.22),
        },
        '&.Mui-focused .MuiOutlinedInput-notchedOutline': {
          borderColor: theme.palette.primary.main,
          borderWidth: 1.5,
        },
        '&.Mui-focused': {
          boxShadow: `0 0 0 3px ${alpha(theme.palette.primary.main, 0.14)}`,
        },
      }),
    },
  },
  MuiButton: {
    styleOverrides: {
      root: ({ theme }) => ({
        borderRadius: radius,
        textTransform: 'none',
        fontWeight: 600,
        letterSpacing: 0,
        '&.MuiButton-containedPrimary': {
          boxShadow: `0 1px 2px ${alpha(theme.palette.primary.main, 0.24)}, 0 4px 12px ${alpha(theme.palette.primary.main, 0.18)}`,
          '&:hover': {
            boxShadow: `0 2px 4px ${alpha(theme.palette.primary.main, 0.26)}, 0 6px 16px ${alpha(theme.palette.primary.main, 0.24)}`,
          },
        },
        '&.MuiButton-containedSecondary': {
          boxShadow: `0 1px 2px ${alpha(theme.palette.secondary.main, 0.24)}, 0 4px 12px ${alpha(theme.palette.secondary.main, 0.18)}`,
        },
      }),
      sizeMedium: {
        height: 40,
        paddingLeft: 18,
        paddingRight: 18,
      },
      sizeSmall: {
        height: 34,
      },
    },
  },
  MuiPaper: {
    styleOverrides: {
      rounded: {
        borderRadius: 12,
      },
    },
  },
  MuiCard: {
    styleOverrides: {
      root: {
        borderRadius: 14,
        overflow: 'hidden',
      },
    },
  },
  MuiCardHeader: {
    styleOverrides: {
      root: {
        padding: '16px 20px',
      },
    },
  },
  MuiCardContent: {
    styleOverrides: {
      root: {
        padding: '20px',
        '&:last-child': {
          paddingBottom: 20,
        },
      },
    },
  },
  MuiDialog: {
    styleOverrides: {
      paper: {
        borderRadius: 16,
        boxShadow: '0 24px 60px rgba(16, 24, 40, 0.16)',
      },
    },
  },
  MuiDialogTitle: {
    styleOverrides: {
      root: {
        fontWeight: 650,
        letterSpacing: '-0.01em',
      },
    },
  },
  MuiPopover: {
    styleOverrides: {
      paper: {
        borderRadius: 12,
      },
    },
  },
  MuiMenu: {
    styleOverrides: {
      paper: {
        borderRadius: 12,
      },
      list: {
        paddingTop: 6,
        paddingBottom: 6,
      },
    },
  },
  MuiMenuItem: {
    styleOverrides: {
      root: ({ theme }) => ({
        borderRadius: 8,
        margin: '2px 6px',
        minHeight: 36,
        '&.Mui-selected': {
          backgroundColor: alpha(theme.palette.primary.main, 0.08),
          '&:hover': {
            backgroundColor: alpha(theme.palette.primary.main, 0.12),
          },
        },
      }),
    },
  },
  MuiListItemButton: {
    styleOverrides: {
      root: ({ theme }) => ({
        borderRadius: 8,
        margin: '2px 8px',
        paddingLeft: 12,
        paddingRight: 12,
        '& .MuiListItemIcon-root': {
          color: theme.palette.text.secondary,
        },
        '&:hover': {
          backgroundColor: alpha(theme.palette.primary.main, 0.05),
          '& .MuiListItemIcon-root': {
            color: theme.palette.primary.main,
          },
        },
        '&.Mui-selected': {
          backgroundColor: alpha(theme.palette.primary.main, 0.08),
          color: theme.palette.primary.main,
          '& .MuiListItemIcon-root': {
            color: theme.palette.primary.main,
          },
          '&:hover': {
            backgroundColor: alpha(theme.palette.primary.main, 0.12),
          },
        },
      }),
    },
  },
  MuiListItemText: {
    styleOverrides: {
      primary: {
        fontWeight: 500,
      },
    },
  },
  MuiTableCell: {
    styleOverrides: {
      root: ({ theme }) => ({
        borderBottom: `1px solid ${theme.palette.divider}`,
      }),
      head: ({ theme }) => ({
        fontWeight: 600,
        color: theme.palette.text.secondary,
        fontSize: '0.8125rem',
        backgroundColor: 'transparent',
      }),
    },
  },
  MuiTableRow: {
    styleOverrides: {
      root: ({ theme }) => ({
        '&:hover': {
          backgroundColor: alpha(theme.palette.primary.main, 0.03),
        },
      }),
    },
  },
  MuiChip: {
    styleOverrides: {
      root: {
        borderRadius: 8,
        fontWeight: 500,
      },
    },
  },
  MuiTooltip: {
    defaultProps: {
      enterDelay: 500,
      enterNextDelay: 500,
    },
    styleOverrides: {
      tooltip: ({ theme }) => ({
        backgroundColor: theme.palette.mode === 'light' ? '#101828' : '#e6eaf2',
        color: theme.palette.mode === 'light' ? '#ffffff' : '#0b0e14',
        borderRadius: 8,
        fontSize: '0.78rem',
        padding: '6px 10px',
        boxShadow: '0 4px 12px rgba(16, 24, 40, 0.14)',
      }),
      arrow: ({ theme }) => ({
        color: theme.palette.mode === 'light' ? '#101828' : '#e6eaf2',
      }),
    },
  },
  MuiSnackbar: {
    defaultProps: {
      anchorOrigin: {
        vertical: 'bottom',
        horizontal: 'center',
      },
    },
  },
  MuiAppBar: {
    styleOverrides: {
      colorInherit: ({ theme }) => ({
        backgroundColor: theme.palette.background.paper,
        color: theme.palette.text.primary,
        borderBottom: `1px solid ${theme.palette.divider}`,
        boxShadow: 'none',
      }),
    },
  },
  MuiDrawer: {
    styleOverrides: {
      paper: ({ theme }) => ({
        backgroundColor: theme.palette.background.paper,
      }),
    },
  },
  MuiTabs: {
    styleOverrides: {
      indicator: {
        height: 3,
        borderTopLeftRadius: 3,
        borderTopRightRadius: 3,
      },
    },
  },
  MuiTab: {
    styleOverrides: {
      root: {
        textTransform: 'none',
        fontWeight: 600,
        minHeight: 44,
      },
    },
  },
  MuiBottomNavigation: {
    styleOverrides: {
      root: ({ theme }) => ({
        backgroundColor: 'transparent',
        height: 60,
      }),
    },
  },
  MuiBottomNavigationAction: {
    styleOverrides: {
      root: ({ theme }) => ({
        color: theme.palette.text.secondary,
        '&.Mui-selected': {
          color: theme.palette.primary.main,
          '& .MuiBottomNavigationAction-label': {
            fontWeight: 600,
          },
        },
        '& .MuiBottomNavigationAction-label': {
          fontSize: '0.7rem',
        },
      }),
    },
  },
  MuiFab: {
    styleOverrides: {
      root: {
        borderRadius: 14,
      },
    },
  },
  MuiAlert: {
    styleOverrides: {
      root: {
        borderRadius: 10,
      },
    },
  },
  MuiAccordion: {
    styleOverrides: {
      root: ({ theme }) => ({
        border: `1px solid ${theme.palette.divider}`,
        borderRadius: 10,
        '&:before': {
          display: 'none',
        },
        '&.Mui-expanded': {
          margin: 0,
        },
      }),
    },
  },
  MuiLinearProgress: {
    styleOverrides: {
      root: {
        borderRadius: 4,
      },
    },
  },
  MuiSkeleton: {
    styleOverrides: {
      root: {
        borderRadius: 8,
      },
    },
  },
  MuiBackdrop: {
    styleOverrides: {
      root: {
        backgroundColor: 'rgba(16, 24, 40, 0.5)',
      },
    },
  },
  MuiAvatar: {
    styleOverrides: {
      root: ({ theme }) => ({
        backgroundColor: alpha(theme.palette.primary.main, 0.12),
      }),
    },
  },
};
