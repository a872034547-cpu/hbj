---
sidebar_position: 10
---

# Fact Checker Agent

The Fact Checker Agent verifies factual claims within your book's content, ensuring accuracy and credibility, particularly important for non-fiction works.

## Overview

This agent identifies and verifies factual statements, providing sources and confidence levels for each claim. It's essential for maintaining the accuracy and credibility of your work.

## Features

### Claim Identification
- Detects factual statements
- Separates facts from opinions
- Identifies statistical claims
- Notes historical references

### Verification Process
- Checks multiple sources
- Validates data points
- Verifies dates and events
- Confirms statistics

### Source Management
- Tracks reference materials
- Rates source reliability
- Documents citations
- Archives verification data

## Output Format

The fact-checking report includes:

```json
{
    "claim": "Original statement",
    "result": "True/False/Partially True/Unverifiable",
    "explanation": "Detailed analysis",
    "sources": [
        {
            "url": "Source URL",
            "reliability": "High/Medium/Low",
            "accessed_date": "Date"
        }
    ],
    "confidence": "Confidence level"
}
```

## Usage

```bash
# Through Project Manager
libriscribe check-facts CHAPTER_NUMBER

# Direct usage
fact_checker.execute(chapter_path)
```

## Verification Levels

1. **Basic Verification**
   - Common knowledge
   - Simple facts
   - General statements
   - Basic dates

2. **Detailed Verification**
   - Statistical data
   - Historical events
   - Scientific claims
   - Technical details

3. **Deep Verification**
   - Complex claims
   - Controversial topics
   - Specialized knowledge
   - Multiple source requirements

## Best Practices

1. **Accuracy First**
   - Verify all claims
   - Check multiple sources
   - Document findings
   - Note uncertainties

2. **Source Management**
   - Evaluate reliability
   - Track citations
   - Archive sources
   - Update references

3. **Quality Control**
   - Review findings
   - Validate sources
   - Cross-reference data
   - Document process

## Integration

Works with:
- Researcher Agent for data gathering
- Content Reviewer for consistency
- Editor Agent for corrections
- Project Manager for oversight

## Error Handling

Manages:
- Unverifiable claims
- Conflicting sources
- Missing references
- Processing errors

## Configuration

Customizable for:
- Verification depth
- Source requirements
- Confidence thresholds
- Citation formats