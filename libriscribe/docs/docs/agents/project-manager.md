---
sidebar_position: 1
---

# Project Manager Agent

The Project Manager Agent is the central coordinator of LibriScribe's book writing process. It manages the workflow and orchestrates the interactions between all other agents.

## Overview

The Project Manager Agent serves as the main interface between the user and LibriScribe's various specialized agents. It handles project initialization, coordinates the execution of different writing stages, and manages the overall book creation process.

## Key Responsibilities

- **Project Initialization**: Creates and configures new book projects
- **Workflow Management**: Coordinates the sequence of agent operations
- **Resource Management**: Handles file organization and agent communication
- **Process Oversight**: Monitors and reports on the progress of book creation

## Command Interface

The Project Manager provides several key commands:

```bash
# Create a new project
libriscribe create PROJECT_NAME --title TITLE --genre GENRE

# Generate initial book concept
libriscribe generate-concept

# Create book outline
libriscribe generate-outline

# Generate character profiles
libriscribe generate-characters

# Create worldbuilding details
libriscribe generate-worldbuilding

# Write specific chapters
libriscribe write-chapter CHAPTER_NUMBER

# Edit chapters
libriscribe edit-chapter CHAPTER_NUMBER

# Format final book
libriscribe format-book

# Conduct research
libriscribe research QUERY
```

## File Structure

The Project Manager creates and maintains the following project structure:

```
project_name/
├── project_data.json     # Project configuration and metadata
├── outline.md           # Book outline
├── characters.json      # Character profiles
├── world.json          # Worldbuilding details
├── chapter_1.md        # Individual chapter files
├── chapter_2.md
└── ...
```

## Error Handling

The Project Manager implements comprehensive error handling:
- Validates project initialization parameters
- Ensures required files exist before agent execution
- Logs errors and provides user-friendly error messages
- Maintains project consistency during failures

## Integration with Other Agents

The Project Manager seamlessly integrates with all other LibriScribe agents:
- Passes necessary context between agents
- Ensures proper sequencing of operations
- Manages file dependencies
- Coordinates multi-agent operations