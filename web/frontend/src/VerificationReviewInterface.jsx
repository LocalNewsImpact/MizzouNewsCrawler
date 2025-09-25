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
  Stack,
  Link as MuiLink
} from '@mui/material';
import {
  CheckCircle,
  Cancel,
  Schedule,
  Speed,
  Source,
  Article,
  Link as LinkIcon
} from '@mui/icons-material';

const VerificationReviewInterface = () => {
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
      const response = await fetch('/api/verification_telemetry/pending?limit=50');
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
      const response = await fetch('/api/verification_telemetry/stats');
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
        verification_id: pendingItems[currentIndex].verification_id,
        human_label: label,
        human_notes: reviewNotes.trim() || null,
        reviewed_by: reviewer
      };

      const response = await fetch('/api/verification_telemetry/feedback', {
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

  const formatUrl = (url) => {
    try {
      const urlObj = new URL(url);
      return urlObj.hostname + urlObj.pathname;
    } catch {
      return url;
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
          🎉 No pending URL verifications!
        </Typography>
        <Typography color="text.secondary">
          All URL classifications have been reviewed.
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
          <Grid item xs={6} sm={2}>
            <Card variant="outlined">
              <CardContent sx={{ textAlign: 'center', py: 1 }}>
                <Typography variant="h6">{stats.pending_review}</Typography>
                <Typography variant="caption" color="text.secondary">
                  Pending Review
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={6} sm={2}>
            <Card variant="outlined">
              <CardContent sx={{ textAlign: 'center', py: 1 }}>
                <Typography variant="h6">{stats.reviewed_correct}</Typography>
                <Typography variant="caption" color="text.secondary">
                  Correct
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={6} sm={2}>
            <Card variant="outlined">
              <CardContent sx={{ textAlign: 'center', py: 1 }}>
                <Typography variant="h6">{stats.reviewed_incorrect}</Typography>
                <Typography variant="caption" color="text.secondary">
                  Incorrect
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={6} sm={2}>
            <Card variant="outlined">
              <CardContent sx={{ textAlign: 'center', py: 1 }}>
                <Typography variant="h6">
                  {stats.storysniffer_accuracy ? 
                    `${(stats.storysniffer_accuracy * 100).toFixed(1)}%` : 'N/A'}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Accuracy
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={6} sm={2}>
            <Card variant="outlined">
              <CardContent sx={{ textAlign: 'center', py: 1 }}>
                <Typography variant="h6">
                  {(stats.article_rate * 100).toFixed(1)}%
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Article Rate
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={6} sm={2}>
            <Card variant="outlined">
              <CardContent sx={{ textAlign: 'center', py: 1 }}>
                <Typography variant="h6">{stats.sources_represented}</Typography>
                <Typography variant="caption" color="text.secondary">
                  Sources
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
              URL Verification Review ({currentIndex + 1} of {pendingItems.length})
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

          {/* URL and Classification Display */}
          <Grid container spacing={3}>
            <Grid item xs={12}>
              <Typography variant="subtitle2" gutterBottom>
                URL:
              </Typography>
              <Box sx={{ 
                p: 2, 
                bgcolor: 'grey.100', 
                borderRadius: 1, 
                fontFamily: 'monospace',
                fontSize: '0.9rem',
                wordBreak: 'break-all'
              }}>
                <MuiLink 
                  href={currentItem.url} 
                  target="_blank" 
                  rel="noopener noreferrer"
                  sx={{ textDecoration: 'none' }}
                >
                  {currentItem.url}
                </MuiLink>
              </Box>
            </Grid>

            <Grid item xs={12} md={6}>
              <Typography variant="subtitle2" gutterBottom>
                StorySniffer Classification:
              </Typography>
              <Box sx={{ 
                p: 2, 
                bgcolor: currentItem.storysniffer_result ? 'success.50' : 'warning.50', 
                borderRadius: 1, 
                display: 'flex',
                alignItems: 'center',
                gap: 1
              }}>
                <Article color={currentItem.storysniffer_result ? 'success' : 'warning'} />
                <Typography variant="h6">
                  {currentItem.storysniffer_result ? 'ARTICLE' : 'NOT ARTICLE'}
                </Typography>
              </Box>
            </Grid>

            <Grid item xs={12} md={6}>
              <Typography variant="subtitle2" gutterBottom>
                Content Preview:
              </Typography>
              <Box sx={{ 
                p: 2, 
                bgcolor: 'grey.50', 
                borderRadius: 1,
                maxHeight: '150px',
                overflow: 'auto'
              }}>
                {currentItem.article_headline && (
                  <Typography variant="subtitle2" gutterBottom>
                    <strong>Headline:</strong> {currentItem.article_headline}
                  </Typography>
                )}
                {currentItem.article_excerpt && (
                  <Typography variant="body2" color="text.secondary">
                    {currentItem.article_excerpt}
                  </Typography>
                )}
                {!currentItem.article_headline && !currentItem.article_excerpt && (
                  <Typography variant="body2" color="text.secondary" style={{ fontStyle: 'italic' }}>
                    No content preview available
                  </Typography>
                )}
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
              {currentItem.verification_confidence !== null && (
                <Chip 
                  icon={<Speed />}
                  label={`Confidence: ${currentItem.verification_confidence.toFixed(2)}`}
                  size="small"
                  color={currentItem.verification_confidence > 0.5 ? 'success' : 'warning'}
                />
              )}
              {currentItem.verification_time_ms && (
                <Chip 
                  icon={<Schedule />}
                  label={`${currentItem.verification_time_ms.toFixed(1)}ms`}
                  size="small"
                />
              )}
              <Chip 
                icon={<LinkIcon />}
                label={formatUrl(currentItem.url)}
                size="small"
                variant="outlined"
              />
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
              placeholder="Add any notes about this classification..."
            />
          </Box>

          {/* Action Buttons */}
          <Box sx={{ mt: 3, display: 'flex', justifyContent: 'center' }}>
            <ButtonGroup variant="contained" disabled={submitting}>
              <Button
                startIcon={<CheckCircle />}
                color="success"
                onClick={() => submitFeedback('correct')}
                size="large"
              >
                Correct Classification
              </Button>
              <Button
                startIcon={<Cancel />}
                color="error"
                onClick={() => submitFeedback('incorrect')}
                size="large"
              >
                Wrong Classification
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

      {/* Help Text */}
      <Box sx={{ mt: 2, p: 2, bgcolor: 'info.50', borderRadius: 1 }}>
        <Typography variant="body2" color="text.secondary">
          <strong>Review Instructions:</strong> Verify if StorySniffer correctly classified this URL. 
          Click "Correct" if the classification matches what you see when visiting the URL. 
          Click "Wrong" if StorySniffer misclassified it (e.g., marked a calendar page as an article).
        </Typography>
      </Box>
    </Box>
  );
};

export default VerificationReviewInterface;