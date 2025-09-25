import React, { useState, useEffect } from 'react';
import {
    Container,
    Paper,
    Typography,
    Grid,
    Card,
    CardContent,
    Box,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    Chip,
    LinearProgress,
    Alert,
    CircularProgress,
    Button,
    Dialog,
    DialogTitle,
    DialogContent,
    DialogActions,
    TextField,
    Tabs,
    Tab,
    List,
    ListItem,
    ListItemText,
    ListItemIcon,
    IconButton
} from '@mui/material';
import {
    CheckCircle as CheckCircleIcon,
    Error as ErrorIcon,
    Warning as WarningIcon,
    Edit as EditIcon,
    Refresh as RefreshIcon,
    LocationOn as LocationOnIcon
} from '@mui/icons-material';

const GazetteerTelemetry = () => {
    const [loading, setLoading] = useState(true);
    const [tabValue, setTabValue] = useState(0);
    const [stats, setStats] = useState(null);
    const [publishers, setPublishers] = useState([]);
    const [failedPublishers, setFailedPublishers] = useState([]);
    const [selectedPublisher, setSelectedPublisher] = useState(null);
    const [editDialogOpen, setEditDialogOpen] = useState(false);
    const [editingAddress, setEditingAddress] = useState({
        source_id: '',
        new_address: '',
        new_city: '',
        new_county: '',
        new_state: '',
        notes: ''
    });

    // Fetch data
    const fetchStats = async () => {
        try {
            const response = await fetch('/api/gazetteer/stats');
            const data = await response.json();
            setStats(data);
        } catch (error) {
            console.error('Error fetching stats:', error);
        }
    };

    const fetchPublishers = async () => {
        try {
            const response = await fetch('/api/gazetteer/publishers');
            const data = await response.json();
            setPublishers(data);
        } catch (error) {
            console.error('Error fetching publishers:', error);
        }
    };

    const fetchFailedPublishers = async () => {
        try {
            const response = await fetch('/api/gazetteer/failed');
            const data = await response.json();
            setFailedPublishers(data);
        } catch (error) {
            console.error('Error fetching failed publishers:', error);
        }
    };

    const refreshData = async () => {
        setLoading(true);
        await Promise.all([
            fetchStats(),
            fetchPublishers(),
            fetchFailedPublishers()
        ]);
        setLoading(false);
    };

    useEffect(() => {
        refreshData();
    }, []);

    // Handle address editing
    const handleEditAddress = (publisher) => {
        setSelectedPublisher(publisher);
        setEditingAddress({
            source_id: publisher.source_id,
            new_address: publisher.address_used || '',
            new_city: publisher.city || '',
            new_county: publisher.county || '',
            new_state: publisher.state || '',
            notes: ''
        });
        setEditDialogOpen(true);
    };

    const handleSaveAddress = async () => {
        try {
            const response = await fetch('/api/gazetteer/update_address', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(editingAddress),
            });

            if (response.ok) {
                setEditDialogOpen(false);
                refreshData();
            } else {
                console.error('Failed to update address');
            }
        } catch (error) {
            console.error('Error updating address:', error);
        }
    };

    const handleReprocess = async (sourceIds) => {
        try {
            const response = await fetch('/api/gazetteer/reprocess', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    source_ids: sourceIds,
                    force_reprocess: true,
                    use_updated_addresses: true
                }),
            });

            if (response.ok) {
                const result = await response.json();
                console.log('Reprocessing queued:', result);
                // Could show a success message here
            }
        } catch (error) {
            console.error('Error triggering reprocess:', error);
        }
    };

    // Format utilities
    const formatPercentage = (value) => `${(value * 100).toFixed(1)}%`;
    const formatNumber = (value) => value ? value.toLocaleString() : '0';

    const getGeocodingStatusIcon = (success) => {
        if (success === true) return <CheckCircleIcon color="success" />;
        if (success === false) return <ErrorIcon color="error" />;
        return <WarningIcon color="warning" />;
    };

    const getGeocodingStatusColor = (success) => {
        if (success === true) return 'success';
        if (success === false) return 'error';
        return 'warning';
    };

    if (loading) {
        return (
            <Container>
                <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
                    <CircularProgress />
                </Box>
            </Container>
        );
    }

    return (
        <Container maxWidth="xl">
            <Box sx={{ mb: 3, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Typography variant="h4" component="h1">
                    Gazetteer Telemetry
                </Typography>
                <Button
                    variant="outlined"
                    startIcon={<RefreshIcon />}
                    onClick={refreshData}
                >
                    Refresh Data
                </Button>
            </Box>

            <Tabs value={tabValue} onChange={(e, newValue) => setTabValue(newValue)} sx={{ mb: 3 }}>
                <Tab label="Overview" />
                <Tab label="Publisher Details" />
                <Tab label="Failed Publishers" />
            </Tabs>

            {/* Overview Tab */}
            {tabValue === 0 && stats && (
                <Grid container spacing={3}>
                    {/* Summary Cards */}
                    <Grid item xs={12} md={3}>
                        <Card>
                            <CardContent>
                                <Typography color="textSecondary" gutterBottom>
                                    Total Publishers
                                </Typography>
                                <Typography variant="h4">
                                    {formatNumber(stats.total_enrichment_attempts)}
                                </Typography>
                            </CardContent>
                        </Card>
                    </Grid>
                    <Grid item xs={12} md={3}>
                        <Card>
                            <CardContent>
                                <Typography color="textSecondary" gutterBottom>
                                    Geocoding Success Rate
                                </Typography>
                                <Typography variant="h4" color="primary">
                                    {formatPercentage(stats.geocoding_success_rate)}
                                </Typography>
                                <LinearProgress
                                    variant="determinate"
                                    value={stats.geocoding_success_rate * 100}
                                    sx={{ mt: 1 }}
                                />
                            </CardContent>
                        </Card>
                    </Grid>
                    <Grid item xs={12} md={3}>
                        <Card>
                            <CardContent>
                                <Typography color="textSecondary" gutterBottom>
                                    Total OSM Elements
                                </Typography>
                                <Typography variant="h4">
                                    {formatNumber(stats.total_osm_elements)}
                                </Typography>
                            </CardContent>
                        </Card>
                    </Grid>
                    <Grid item xs={12} md={3}>
                        <Card>
                            <CardContent>
                                <Typography color="textSecondary" gutterBottom>
                                    Avg Elements/Publisher
                                </Typography>
                                <Typography variant="h4">
                                    {formatNumber(stats.avg_elements_per_publisher)}
                                </Typography>
                            </CardContent>
                        </Card>
                    </Grid>

                    {/* Geocoding Methods */}
                    <Grid item xs={12} md={6}>
                        <Paper sx={{ p: 2 }}>
                            <Typography variant="h6" gutterBottom>
                                Geocoding Methods
                            </Typography>
                            <List>
                                {Object.entries(stats.geocoding_methods).map(([method, count]) => (
                                    <ListItem key={method}>
                                        <ListItemIcon>
                                            <LocationOnIcon />
                                        </ListItemIcon>
                                        <ListItemText
                                            primary={method.replace('_', ' ').toUpperCase()}
                                            secondary={`${count} publishers`}
                                        />
                                    </ListItem>
                                ))}
                            </List>
                        </Paper>
                    </Grid>

                    {/* Top OSM Categories */}
                    <Grid item xs={12} md={6}>
                        <Paper sx={{ p: 2 }}>
                            <Typography variant="h6" gutterBottom>
                                Top OSM Categories
                            </Typography>
                            <List>
                                {Object.entries(stats.top_categories).map(([category, count]) => (
                                    <ListItem key={category}>
                                        <ListItemText
                                            primary={category.charAt(0).toUpperCase() + category.slice(1)}
                                            secondary={`${formatNumber(count)} elements`}
                                        />
                                    </ListItem>
                                ))}
                            </List>
                        </Paper>
                    </Grid>
                </Grid>
            )}

            {/* Publisher Details Tab */}
            {tabValue === 1 && (
                <TableContainer component={Paper}>
                    <Table>
                        <TableHead>
                            <TableRow>
                                <TableCell>Publisher</TableCell>
                                <TableCell>Location</TableCell>
                                <TableCell>Geocoding</TableCell>
                                <TableCell>OSM Elements</TableCell>
                                <TableCell>Processing Time</TableCell>
                                <TableCell>Actions</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {publishers.map((publisher) => (
                                <TableRow key={publisher.source_id}>
                                    <TableCell>
                                        <Typography variant="body2" fontWeight="medium">
                                            {publisher.source_name}
                                        </Typography>
                                    </TableCell>
                                    <TableCell>
                                        {publisher.city}, {publisher.county}, {publisher.state}
                                    </TableCell>
                                    <TableCell>
                                        <Box display="flex" alignItems="center" gap={1}>
                                            {getGeocodingStatusIcon(publisher.geocoding_success)}
                                            <Chip
                                                label={publisher.geocoding_method || 'N/A'}
                                                size="small"
                                                color={getGeocodingStatusColor(publisher.geocoding_success)}
                                                variant="outlined"
                                            />
                                        </Box>
                                    </TableCell>
                                    <TableCell>
                                        {formatNumber(publisher.total_osm_elements)}
                                    </TableCell>
                                    <TableCell>
                                        {publisher.processing_time_seconds
                                            ? `${publisher.processing_time_seconds.toFixed(1)}s`
                                            : 'N/A'}
                                    </TableCell>
                                    <TableCell>
                                        <IconButton
                                            size="small"
                                            onClick={() => handleEditAddress(publisher)}
                                        >
                                            <EditIcon />
                                        </IconButton>
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </TableContainer>
            )}

            {/* Failed Publishers Tab */}
            {tabValue === 2 && (
                <Box>
                    <Alert severity="warning" sx={{ mb: 2 }}>
                        These publishers had geocoding failures or incomplete processing.
                        You can edit their addresses and re-run processing.
                    </Alert>
                    <TableContainer component={Paper}>
                        <Table>
                            <TableHead>
                                <TableRow>
                                    <TableCell>Publisher</TableCell>
                                    <TableCell>Location</TableCell>
                                    <TableCell>Issue</TableCell>
                                    <TableCell>Address Used</TableCell>
                                    <TableCell>Actions</TableCell>
                                </TableRow>
                            </TableHead>
                            <TableBody>
                                {failedPublishers.map((publisher) => (
                                    <TableRow key={publisher.source_id}>
                                        <TableCell>
                                            <Typography variant="body2" fontWeight="medium">
                                                {publisher.source_name}
                                            </Typography>
                                        </TableCell>
                                        <TableCell>
                                            {publisher.city}, {publisher.county}, {publisher.state}
                                        </TableCell>
                                        <TableCell>
                                            <Chip
                                                label={
                                                    publisher.geocoding_success === false
                                                        ? 'Geocoding Failed'
                                                        : publisher.enrichment_success === false
                                                        ? 'Enrichment Failed'
                                                        : 'No OSM Data'
                                                }
                                                color="error"
                                                size="small"
                                            />
                                        </TableCell>
                                        <TableCell>
                                            <Typography variant="body2" color="textSecondary">
                                                {publisher.address_used || 'No address used'}
                                            </Typography>
                                        </TableCell>
                                        <TableCell>
                                            <Box display="flex" gap={1}>
                                                <IconButton
                                                    size="small"
                                                    onClick={() => handleEditAddress(publisher)}
                                                >
                                                    <EditIcon />
                                                </IconButton>
                                                <IconButton
                                                    size="small"
                                                    onClick={() => handleReprocess([publisher.source_id])}
                                                >
                                                    <RefreshIcon />
                                                </IconButton>
                                            </Box>
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </TableContainer>
                </Box>
            )}

            {/* Edit Address Dialog */}
            <Dialog open={editDialogOpen} onClose={() => setEditDialogOpen(false)} maxWidth="sm" fullWidth>
                <DialogTitle>Edit Publisher Address</DialogTitle>
                <DialogContent>
                    <Box sx={{ mt: 2 }}>
                        <Typography variant="h6" gutterBottom>
                            {selectedPublisher?.source_name}
                        </Typography>
                        <Grid container spacing={2}>
                            <Grid item xs={12}>
                                <TextField
                                    fullWidth
                                    label="Address"
                                    value={editingAddress.new_address}
                                    onChange={(e) => setEditingAddress({
                                        ...editingAddress,
                                        new_address: e.target.value
                                    })}
                                />
                            </Grid>
                            <Grid item xs={12} sm={4}>
                                <TextField
                                    fullWidth
                                    label="City"
                                    value={editingAddress.new_city}
                                    onChange={(e) => setEditingAddress({
                                        ...editingAddress,
                                        new_city: e.target.value
                                    })}
                                />
                            </Grid>
                            <Grid item xs={12} sm={4}>
                                <TextField
                                    fullWidth
                                    label="County"
                                    value={editingAddress.new_county}
                                    onChange={(e) => setEditingAddress({
                                        ...editingAddress,
                                        new_county: e.target.value
                                    })}
                                />
                            </Grid>
                            <Grid item xs={12} sm={4}>
                                <TextField
                                    fullWidth
                                    label="State"
                                    value={editingAddress.new_state}
                                    onChange={(e) => setEditingAddress({
                                        ...editingAddress,
                                        new_state: e.target.value
                                    })}
                                />
                            </Grid>
                            <Grid item xs={12}>
                                <TextField
                                    fullWidth
                                    label="Notes"
                                    multiline
                                    rows={3}
                                    value={editingAddress.notes}
                                    onChange={(e) => setEditingAddress({
                                        ...editingAddress,
                                        notes: e.target.value
                                    })}
                                />
                            </Grid>
                        </Grid>
                    </Box>
                </DialogContent>
                <DialogActions>
                    <Button onClick={() => setEditDialogOpen(false)}>
                        Cancel
                    </Button>
                    <Button
                        onClick={handleSaveAddress}
                        variant="contained"
                        color="primary"
                    >
                        Save & Reprocess
                    </Button>
                </DialogActions>
            </Dialog>
        </Container>
    );
};

export default GazetteerTelemetry;