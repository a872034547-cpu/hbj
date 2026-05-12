---
sidebar_position: 11
---

# Plagiarism Checker Agent

The Plagiarism Checker Agent identifies potential plagiarism issues in your book's content, ensuring originality and proper attribution.

## Overview

This agent analyzes text for similarity with existing works, identifies common phrases, and helps maintain the originality of your content while ensuring proper attribution when needed.

## Features

### Content Analysis
- Text similarity detection
- Common phrase identification
- Structure comparison
- Style analysis

### Similarity Detection
- Exact matches
- Paraphrase detection
- Structure similarity
- Idea originality

### Report Generation
- Detailed findings
- Similarity scores
- Source references
- Improvement suggestions

## Detection Methods

### Text Analysis
- Exact phrase matching
- Fuzzy matching
- Structural comparison
- Stylistic analysis

### Pattern Recognition
- Common phrases
- Structural patterns
- Writing styles
- Source attribution

### Source Comparison
- Reference databases
- Common sources
- Genre conventions
- Standard phrases

## Output Format

```json
{
    "text": "Potentially problematic text",
    "similarity_score": 0.85,
    "source": "Possible source or explanation",
    "suggested_changes": "Improvement recommendations",
    "severity": "High/Medium/Low"
}
```

## Usage

```bash
# Through Project Manager
libriscribe check-plagiarism CHAPTER_NUMBER

# Direct usage
plagiarism_checker.execute(chapter_path)
```

## Best Practices

1. **Content Review**
   - Regular checks
   - Chapter analysis
   - Source tracking
   - Attribution review

2. **Quality Control**
   - False positive review
   - Context consideration
   - Genre conventions
   - Standard phrases

3. **Documentation**
   - Track findings
   - Record changes
   - Document sources
   - Maintain records

## Process Flow

1. **Initial Scan**
   - Text processing
   - Pattern matching
   - Similarity detection
   - Score calculation

2. **Detailed Analysis**
   - Context review
   - Source comparison
   - Pattern verification
   - Attribution check

3. **Report Generation**
   - Finding compilation
   - Score assessment
   - Recommendation creation
   - Documentation

## Integration

Works with:
- Content Reviewer for consistency
- Editor Agent for revisions
- Fact Checker for attribution
- Project Manager for oversight

## Error Handling

Manages:
- False positives
- Processing errors
- Source conflicts
- Analysis failures

## Configuration Options

Customizable for:
- Similarity thresholds
- Source databases
- Genre considerations
- Attribution requirements