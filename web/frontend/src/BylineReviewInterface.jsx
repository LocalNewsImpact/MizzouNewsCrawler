import React, { useState, useEffect } from 'react';
import {
  Box,
  Card,
  CardContent,
  Typography,
  Button,
  ButtonGroup,
  TextField,
  Chip,
  Grid,
  Alert,
  CircularProgress,
  Divider,
  Stack
} from '@mui/material';
import {
  CheckCircle,
  Cancel,
  PartiallyCloudyDay,
  Schedule,
  Speed,
  Source
} from '@mui/icons-material';

const BylineReviewInterface = () => {
  const [pendingItems, setPendingItems] = useState([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [stats, setStats] = useState(null);
  const [reviewNotes, setReviewNotes] = useState('');
  const [reviewer] = useState('human_reviewer'); // Could be made configurable

  useEffect(() => {
    fetchPendingItems();
    fetchStats();
  }, []);

  const fetchPendingItems = async () => {
    try {
      setLoading(true);
      const response = await fetch('/api/byline_telemetry/pending?limit=50');
      const data = await response.json();
      if (data.status === 'ok') {
        setPendingItems(data.items);
        setCurrentIndex(0);
      } else {
        setError('Failed to fetch pending items');
      }
    } catch (err) {
      setError(`Error fetching data: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const fetchStats = async () => {
    try {
      const response = await fetch('/api/byline_telemetry/stats');
      const data = await response.json();
      setStats(data);
    } catch (err) {
      console.error('Error fetching stats:', err);
    }
  };

  const submitFeedback = async (label) => {
    if (!pendingItems[currentIndex]) return;

    setSubmitting(true);
    try {
      const feedback = {
        telemetry_id: pendingItems[currentIndex].telemetry_id,
        human_label: label,
        human_notes: reviewNotes.trim() || null,
        reviewed_by: reviewer
      };

      const response = await fetch('/api/byline_telemetry/feedback', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(feedback),
      });

      const data = await response.json();
      if (data.status === 'ok') {
        // Remove reviewed item and move to next
        const newItems = [...pendingItems];
        newItems.splice(currentIndex, 1);
        setPendingItems(newItems);
        
        // Adjust index if needed
        if (currentIndex >= newItems.length && newItems.length > 0) {
          setCurrentIndex(newItems.length - 1);
        }
        
        // Clear notes for next item
        setReviewNotes('');
        
        // Refresh stats
        fetchStats();
      } else {
        setError('Failed to submit feedback');
      }
    } catch (err) {
      setError(`Error submitting feedback: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const goToNext = () => {
    if (currentIndex < pendingItems.length - 1) {
      setCurrentIndex(currentIndex + 1);
      setReviewNotes('');
    }
  };

  const goToPrevious = () => {
    if (currentIndex > 0) {
      setCurrentIndex(currentIndex - 1);
      setReviewNotes('');
    }
  };

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Alert severity="error" sx={{ m: 2 }}>
        {error}
        <Button onClick={() => { setError(null); fetchPendingItems(); }} sx={{ ml: 2 }}>
          Retry
        </Button>
      </Alert>
    );
  }

  if (pendingItems.length === 0) {
    return (
      <Box sx={{ p: 3, textAlign: 'center' }}>
        <Typography variant="h6" gutterBottom>
          🎉 No pending byline reviews!
        </Typography>
        <Typography color="text.secondary">
          All byline extractions have been reviewed.
        </Typography>
        <Button onClick={fetchPendingItems} sx={{ mt: 2 }}>
          Refresh
        </Button>
      </Box>
    );
  }

  const currentItem = pendingItems[currentIndex];

  return (
    <Box sx={{ p: 3 }}>
      {/* Stats Header */}
      {stats && (
        <Grid container spacing={2} sx={{ mb: 3 }}>
          <Grid item xs={6} sm={3}>
            <Card variant="outlined">
              <CardContent sx={{ textAlign: 'center', py: 1 }}>
                <Typography variant="h6">{stats.pending_review}</Typography>
                <Typography variant="caption" color="text.secondary">
                  Pending Review
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={6} sm={3}>
            <Card variant="outlined">
              <CardContent sx={{ textAlign: 'center', py: 1 }}>
                <Typography variant="h6">{stats.reviewed_correct}</Typography>
                <Typography variant="caption" color="text.secondary">
                  Correct
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={6} sm={3}>
            <Card variant="outlined">
              <CardContent sx={{ textAlign: 'center', py: 1 }}>
                <Typography variant="h6">{stats.reviewed_incorrect}</Typography>
                <Typography variant="caption" color="text.secondary">
                  Incorrect
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={6} sm={3}>
            <Card variant="outlined">
              <CardContent sx={{ textAlign: 'center', py: 1 }}>
                <Typography variant="h6">
                  {stats.avg_confidence_score.toFixed(2)}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Avg Confidence
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      {/* Main Review Interface */}
      <Card>
        <CardContent>
          {/* Progress Indicator */}
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Typography variant="h6">
              Byline Review ({currentIndex + 1} of {pendingItems.length})
            </Typography>
            <Stack direction="row" spacing={1}>
              <Button 
                size="small" 
                onClick={goToPrevious} 
                disabled={currentIndex === 0}
              >
                Previous
              </Button>
              <Button 
                size="small" 
                onClick={goToNext} 
                disabled={currentIndex === pendingItems.length - 1}
              >
                Next
              </Button>
            </Stack>
          </Box>

          <Divider sx={{ mb: 2 }} />

          {/* Byline Transformation Display */}
          <Grid container spacing={3}>
            <Grid item xs={12} md={6}>
              <Typography variant="subtitle2" gutterBottom>
                Original Byline:
              </Typography>
              <Box sx={{ 
                p: 2, 
                bgcolor: 'grey.100', 
                borderRadius: 1, 
                fontFamily: 'monospace',
                fontSize: '0.9rem'
              }}>
                "{currentItem.raw_byline}"
              </Box>
            </Grid>

            <Grid item xs={12} md={6}>
              <Typography variant="subtitle2" gutterBottom>
                Cleaned Result:
              </Typography>
              <Box sx={{ 
                p: 2, 
                bgcolor: 'success.50', 
                borderRadius: 1, 
                fontFamily: 'monospace',
                fontSize: '0.9rem'
              }}>
                "{currentItem.final_authors_display}"
              </Box>
            </Grid>
          </Grid>

          {/* Metadata */}
          <Box sx={{ mt: 3 }}>
            <Stack direction="row" spacing={2} flexWrap="wrap">
              <Chip 
                icon={<Source />}
                label={`Source: ${currentItem.source_name}`}
                size="small"
              />
              <Chip 
                icon={<Speed />}
                label={`Confidence: ${currentItem.confidence_score.toFixed(2)}`}
                size="small"
                color={currentItem.confidence_score > 0.5 ? 'success' : 'warning'}
              />
              <Chip 
                icon={<Schedule />}
                label={`${currentItem.processing_time_ms.toFixed(1)}ms`}
                size="small"
              />
              {currentItem.has_wire_service && (
                <Chip 
                  label="Wire Service"
                  size="small"
                  color="info"
                />
              )}
              {currentItem.source_name_removed && (
                <Chip 
                  label="Source Removed"
                  size="small"
                  variant="outlined"
                />
              )}
            </Stack>
          </Box>

          {/* Review Notes */}
          <Box sx={{ mt: 3 }}>
            <TextField
              fullWidth
              multiline
              rows={2}
              label="Review Notes (optional)"
              value={reviewNotes}
              onChange={(e) => setReviewNotes(e.target.value)}
              placeholder="Add any notes about this extraction..."
            />
          </Box>

          {/* Action Buttons */}
          <Box sx={{ mt: 3, display: 'flex', justifyContent: 'center' }}>
            <ButtonGroup variant="contained" disabled={submitting}>
              <Button
                startIcon={<CheckCircle />}
                color="success"
                onClick={() => submitFeedback('correct')}
              >
                Correct
              </Button>
              <Button
                startIcon={<PartiallyCloudyDay />}
                color="warning"
                onClick={() => submitFeedback('partial')}
              >
                Partial
              </Button>
              <Button
                startIcon={<Cancel />}
                color="error"
                onClick={() => submitFeedback('incorrect')}
              >
                Incorrect
              </Button>
            </ButtonGroup>
          </Box>

          {submitting && (
            <Box sx={{ display: 'flex', justifyContent: 'center', mt: 2 }}>
              <CircularProgress size={24} />
            </Box>
          )}
        </CardContent>
      </Card>
    </Box>
  );
};

export default BylineReviewInterface;