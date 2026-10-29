import { Box, Card, CardContent, Typography } from '@mui/material';

/**
 * The headline numbers at the top of the tachograph page.
 *
 * <p>Laid out with CSS grid rather than MUI's Grid so the row reflows on a phone without the
 * component API churn Grid has been through, and so a card can be highlighted when it is
 * reporting something that needs attention.
 */
const TachographStatCards = ({ stats }) => (
  <Box
    sx={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
      gap: 2,
      mb: 3,
    }}
  >
    {stats.map((stat) => (
      <Card
        key={stat.label}
        variant="outlined"
        sx={{
          borderColor: stat.alert ? 'error.main' : undefined,
          borderWidth: stat.alert ? 2 : 1,
        }}
      >
        <CardContent>
          <Typography variant="caption" color="text.secondary" display="block" noWrap>
            {stat.label}
          </Typography>
          <Typography variant="h5" color={stat.alert ? 'error.main' : 'text.primary'}>
            {stat.value}
          </Typography>
          {stat.detail && (
            <Typography variant="caption" color="text.secondary">
              {stat.detail}
            </Typography>
          )}
        </CardContent>
      </Card>
    ))}
  </Box>
);

export default TachographStatCards;
