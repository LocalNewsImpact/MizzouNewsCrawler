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
  Paper,
  Accordion,
  AccordionSummary,
  AccordionDetails
} from '@mui/material';
import {
  CheckCircle,
  Cancel,
  EditNote,
  Schedule,
  Code,
  Person,
  BugReport,
  Build,
  Article,
  ExpandMore
} from '@mui/icons-material';

const CodeReviewInterface = () => {
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
      const response = await fetch('/api/code_review_telemetry/pending?limit=50');
      const data = await response.json();
      if (data.status === 'ok') {
        setPendingItems(data.items);
        setCurrentIndex(0);
      } else {
        setError('Failed to fetch pending code reviews');
      }
    } catch (err) {
      setError(`Error fetching data: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const fetchStats = async () => {
    try {
      const response = await fetch('/api/code_review_telemetry/stats');
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
        review_id: pendingItems[currentIndex].review_id,
        human_label: label,
        human_notes: reviewNotes,
        reviewed_by: reviewer
      };

      const response = await fetch('/api/code_review_telemetry/feedback', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(feedback),
      });

      const result = await response.json();
      if (result.status === 'ok') {
        // Remove the reviewed item and move to next
        const newItems = [...pendingItems];
        newItems.splice(currentIndex, 1);
        setPendingItems(newItems);
        
        // Adjust current index if necessary
        if (currentIndex >= newItems.length && newItems.length > 0) {
          setCurrentIndex(newItems.length - 1);
        }
        
        // Clear notes for next review
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

  const goToPrevious = () => {
    if (currentIndex > 0) {
      setCurrentIndex(currentIndex - 1);
      setReviewNotes('');
    }
  };

  const goToNext = () => {
    if (currentIndex < pendingItems.length - 1) {
      setCurrentIndex(currentIndex + 1);
      setReviewNotes('');
    }
  };

  const getPriorityColor = (priority) => {
    switch (priority) {
      case 'critical': return 'error';
      case 'high': return 'warning'; 
      case 'medium': return 'info';
      case 'low': return 'success';
      default: return 'default';
    }
  };

  const getChangeTypeIcon = (changeType) => {
    switch (changeType) {
      case 'bugfix': return <BugReport />;
      case 'feature': return <Build />;
      case 'refactor': return <Code />;
      case 'documentation': return <Article />;
      default: return <Code />;
    }
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '400px' }}>
        <CircularProgress />
        <Typography sx={{ ml: 2 }}>Loading code reviews...</Typography>
      </Box>
    );
  }

  if (error) {
    return (
      <Alert severity="error" sx={{ m: 2 }}>
        {error}
        <Button onClick={fetchPendingItems} sx={{ ml: 2 }}>
          Retry
        </Button>
      </Alert>
    );
  }

  if (pendingItems.length === 0) {
    return (
      <Box sx={{ textAlign: 'center', py: 8 }}>
        <CheckCircle sx={{ fontSize: 64, color: 'success.main', mb: 2 }} />
        <Typography variant="h5" gutterBottom>
          🎉 No pending code reviews!
        </Typography>
        <Typography color="text.secondary">
          All code changes have been reviewed.
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
                <Typography variant="h6">{stats.approved}</Typography>
                <Typography variant="caption" color="text.secondary">
                  Approved
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={6} sm={3}>
            <Card variant="outlined">
              <CardContent sx={{ textAlign: 'center', py: 1 }}>
                <Typography variant="h6">{stats.rejected}</Typography>
                <Typography variant="caption" color="text.secondary">
                  Rejected
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={6} sm={3}>
            <Card variant="outlined">
              <CardContent sx={{ textAlign: 'center', py: 1 }}>
                <Typography variant="h6">{stats.needs_changes}</Typography>
                <Typography variant="caption" color="text.secondary">
                  Needs Changes
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
              Code Review ({currentIndex + 1} of {pendingItems.length})
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

          {/* Code Review Information */}
          <Grid container spacing={3}>
            <Grid item xs={12} md={8}>
              <Stack spacing={2}>
                {/* Title and Priority */}
                <Box>
                  <Typography variant="h5" gutterBottom>
                    {currentItem.title}
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
                    <Chip 
                      label={currentItem.priority}
                      color={getPriorityColor(currentItem.priority)}
                      size="small"
                    />
                    <Chip 
                      icon={getChangeTypeIcon(currentItem.change_type)}
                      label={currentItem.change_type}
                      variant="outlined"
                      size="small"
                    />
                  </Box>
                </Box>

                {/* Author and Branches */}
                <Box>
                  <Typography variant="subtitle2" gutterBottom>
                    <Person sx={{ fontSize: 16, mr: 1, verticalAlign: 'text-bottom' }} />
                    Author: {currentItem.author}
                  </Typography>
                  {currentItem.source_branch && (
                    <Typography variant="body2" color="text.secondary">
                      {currentItem.source_branch} → {currentItem.target_branch || 'main'}
                    </Typography>
                  )}
                </Box>

                {/* Description */}
                <Box>
                  <Typography variant="subtitle2" gutterBottom>
                    Description:
                  </Typography>
                  <Typography variant="body2" sx={{ 
                    p: 2, 
                    bgcolor: 'grey.50', 
                    borderRadius: 1,
                    whiteSpace: 'pre-wrap'
                  }}>
                    {currentItem.description || 'No description provided'}
                  </Typography>
                </Box>

                {/* File Path */}
                {currentItem.file_path && (
                  <Box>
                    <Typography variant="subtitle2" gutterBottom>
                      File:
                    </Typography>
                    <Typography variant="body2" sx={{ fontFamily: 'monospace', bgcolor: 'grey.100', p: 1, borderRadius: 1 }}>
                      {currentItem.file_path}
                    </Typography>
                  </Box>
                )}

                {/* Code Diff */}
                {currentItem.code_diff && (
                  <Accordion>
                    <AccordionSummary
                      expandIcon={<ExpandMore />}
                      aria-controls="code-diff-content"
                      id="code-diff-header"
                    >
                      <Typography variant="subtitle2">
                        <Code sx={{ mr: 1, verticalAlign: 'text-bottom' }} />
                        View Code Changes
                      </Typography>
                    </AccordionSummary>
                    <AccordionDetails>
                      <Paper sx={{ p: 2, bgcolor: 'grey.50' }}>
                        <Typography 
                          variant="body2" 
                          component="pre" 
                          sx={{ 
                            fontFamily: 'monospace', 
                            whiteSpace: 'pre-wrap',
                            fontSize: '0.875rem',
                            lineHeight: 1.4
                          }}
                        >
                          {currentItem.code_diff}
                        </Typography>
                      </Paper>
                    </AccordionDetails>
                  </Accordion>
                )}
              </Stack>
            </Grid>

            {/* Review Actions */}
            <Grid item xs={12} md={4}>
              <Paper sx={{ p: 2, bgcolor: 'grey.50' }}>
                <Typography variant="h6" gutterBottom>
                  Review Actions
                </Typography>
                
                {/* Notes Input */}
                <TextField
                  fullWidth
                  multiline
                  rows={4}
                  label="Review Notes"
                  value={reviewNotes}
                  onChange={(e) => setReviewNotes(e.target.value)}
                  placeholder="Add your review comments..."
                  sx={{ mb: 2 }}
                />

                {/* Action Buttons */}
                <Stack spacing={1}>
                  <Button
                    variant="contained"
                    color="success"
                    startIcon={<CheckCircle />}
                    onClick={() => submitFeedback('approved')}
                    disabled={submitting}
                    fullWidth
                  >
                    Approve
                  </Button>
                  
                  <Button
                    variant="contained" 
                    color="warning"
                    startIcon={<EditNote />}
                    onClick={() => submitFeedback('needs_changes')}
                    disabled={submitting}
                    fullWidth
                  >
                    Request Changes
                  </Button>
                  
                  <Button
                    variant="contained"
                    color="error"
                    startIcon={<Cancel />}
                    onClick={() => submitFeedback('rejected')}
                    disabled={submitting}
                    fullWidth
                  >
                    Reject
                  </Button>
                </Stack>

                {submitting && (
                  <Box sx={{ display: 'flex', justifyContent: 'center', mt: 2 }}>
                    <CircularProgress size={24} />
                    <Typography sx={{ ml: 1 }}>Submitting...</Typography>
                  </Box>
                )}

                {/* Metadata */}
                <Divider sx={{ my: 2 }} />
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    <Schedule sx={{ fontSize: 14, mr: 0.5, verticalAlign: 'text-bottom' }} />
                    Created: {new Date(currentItem.created_at).toLocaleDateString()}
                  </Typography>
                </Box>
              </Paper>
            </Grid>
          </Grid>
        </CardContent>
      </Card>
    </Box>
  );
};

export default CodeReviewInterface;