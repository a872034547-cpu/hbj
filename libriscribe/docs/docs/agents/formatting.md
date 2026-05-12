---
sidebar_position: 13
---

# Formatting Agent

The Formatting Agent combines all generated chapters into a single, well-formatted document, preparing your book for export in various formats.

## Overview

This agent handles the final stage of book production, combining individual chapters into a cohesive document while maintaining consistent formatting and style. It supports both Markdown and PDF output formats.

## Features

### Document Assembly
- Chapter combination
- Content organization
- Structure maintenance
- Format consistency

### Formatting Options
- Title page creation
- Chapter formatting
- Section breaks
- Page layout
- Typography settings

### Output Formats
- Markdown (.md)
- PDF document
- Consistent styling
- Professional layout

## Document Structure

### Title Page
```markdown
# [Book Title]
## By [Author Name]
**Genre:** [Genre]
```

### Chapter Format
```markdown
# Chapter [Number]: [Title]

[Chapter content with proper formatting]

## Scene breaks where appropriate

[Continued content...]
```

## Process Flow

1. **Content Collection**
   - Gather chapter files
   - Load project data
   - Verify content
   - Check structure

2. **Format Processing**
   - Apply formatting
   - Add title page
   - Process chapters
   - Insert breaks

3. **Output Generation**
   - Format conversion
   - Style application
   - Quality checks
   - File generation

## Usage

```bash
# Through Project Manager
libriscribe format-book

# Direct usage
formatting.execute(project_dir, output_path)
```

## Supported Features

### Markdown Format
- Headers
- Emphasis
- Lists
- Blockquotes
- Code blocks
- Links
- Images

### PDF Format
- Font selection
- Page sizing
- Margins
- Headers/footers
- Page numbers
- Chapter breaks

## Best Practices

1. **Preparation**
   - Verify content
   - Check structure
   - Validate files
   - Review settings

2. **Quality Control**
   - Check formatting
   - Verify styles
   - Review layout
   - Test output

3. **File Management**
   - Organize content
   - Back up files
   - Version control
   - Archive outputs

## Integration

Works with:
- Editor Agent for final checks
- Style Editor for consistency
- Project Manager for coordination
- All content-generating agents

## Error Handling

Manages:
- Missing files
- Format errors
- Processing issues
- Style conflicts

## Configuration

Customizable for:
- Output format
- Style preferences
- Page layout
- Typography
- File structure