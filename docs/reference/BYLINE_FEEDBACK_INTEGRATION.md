# Byline Telemetry Human Feedback Integration

## Overview

Your React frontend now includes a comprehensive byline telemetry review system that allows human reviewers to label byline cleaning results for ML training data collection.

## What's Integrated

### 1. Backend API Extensions
- **New endpoints** in `web/reviewer_api.py`:
  - `GET /api/byline_telemetry/pending` - Get items needing review
  - `POST /api/byline_telemetry/feedback` - Submit human feedback  
  - `GET /api/byline_telemetry/stats` - Review statistics
  - `GET /api/byline_telemetry/training_data` - Export labeled data

### 2. Database Schema Updates
- Added human feedback columns to `byline_cleaning_telemetry` table:
  - `human_label` - "correct", "incorrect", "partial"
  - `human_notes` - Optional reviewer comments
  - `reviewed_by` - Reviewer identifier
  - `reviewed_at` - Review timestamp

### 3. React Frontend Component
- **New tab**: "Byline Review" in your main navigation
- **Component**: `BylineReviewInterface.jsx` with:
  - Side-by-side comparison of original → cleaned bylines
  - Metadata display (confidence, processing time, source)
  - Three-button feedback system (Correct/Partial/Incorrect)
  - Progress tracking and statistics dashboard
  - Navigation between pending items

## Usage Workflow

### 1. Start the System
```bash
# Start backend API
cd web
python reviewer_api.py

# Start frontend (separate terminal)
cd web/frontend  
npm run dev
```

### 2. Generate Telemetry Data
```bash
# Run extraction to capture byline cleaning telemetry
python -m src.cli.main extract --limit 10 --batches 1
```

### 3. Review in Web Interface
1. Open browser to your frontend URL
2. Click "Byline Review" tab
3. Review each byline transformation:
   - Compare original vs cleaned result
   - Check confidence score and metadata
   - Click **Correct**, **Partial**, or **Incorrect**
   - Add optional notes for complex cases

### 4. Export Training Data
```bash
# Get labeled data for ML training
curl "http://localhost:8000/api/byline_telemetry/training_data?min_confidence=0.0&format=csv"
```

## Human Feedback Labels

- **Correct**: Byline cleaning worked perfectly
- **Partial**: Some authors extracted correctly, some missed/wrong
- **Incorrect**: Completely wrong or failed extraction

## ML Training Integration

The system captures rich features for ML model development:

**Raw Features:**
- Original byline text and metadata
- Transformation steps and confidence scores  
- Processing characteristics

**Human Labels:**
- Quality assessment (correct/partial/incorrect)
- Reviewer notes for edge cases
- Timestamp tracking for data versioning

**Engineered Features:**
- Complexity scores, word counts
- Pattern matching indicators
- Source-specific characteristics

## Integration Benefits

1. **Seamless Workflow**: Human feedback integrated into existing web interface
2. **Rich Context**: Reviewers see full transformation metadata
3. **Scalable**: Multiple reviewers can work simultaneously
4. **Traceable**: All feedback timestamped and attributed  
5. **ML Ready**: Labeled data automatically formatted for training

## Next Steps

1. **Scale Collection**: Run large extractions to build substantial training dataset
2. **Multi-Reviewer**: Add reviewer authentication and inter-rater reliability tracking
3. **Active Learning**: Use model uncertainty to prioritize which items need human review
4. **Continuous Learning**: Retrain models periodically with new labeled data

Your telemetry system is now production-ready for collecting high-quality ML training data through your existing React web interface!