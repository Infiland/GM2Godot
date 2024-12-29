# Contributing to GM2Godot

Thank you for your interest in contributing to GM2Godot! We aim to make GameMaker to Godot conversion as smooth as possible, and your contributions help make this goal a reality.

## Getting Started

1. **Fork the Repository**
   - Click the "Fork" button at the top right of the [GM2Godot repository](https://github.com/Infiland/GM2Godot)
   - Clone your fork locally:
     ```bash
     git clone https://github.com/YOUR_USERNAME/GM2Godot
     cd GM2Godot
     ```

2. **Set Up Development Environment**
   - Install Python 3.9.0 or later
   - Install required packages:
     ```bash
     pip install Pillow markdown2 tkhtmlview
     ```
   - For Linux users, install additional dependencies:
     ```bash
     sudo apt-get install python3-tk python3-pil python3-pil.imagetk python3-markdown2
     ```

## Development Guidelines

### Code Style
- Follow PEP 8 guidelines for Python code
- Use meaningful variable and function names
- Add comments for complex logic
- Keep functions focused and concise
- Use type hints where appropriate

### UI Development
- Maintain consistency with the existing dark theme
- Use the modern widget classes in `src/gui/modern_widgets.py`
- Follow the existing pattern for styling and layout
- Test UI changes at different window sizes

### Asset Conversion
When adding new asset conversion features:
1. Create a new converter class in `src/conversion/`
2. Follow the existing converter pattern
3. Add appropriate error handling
4. Include progress reporting
5. Add the new feature to the settings UI

## Making Changes

1. **Create a Branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make Your Changes**
   - Write clean, documented code
   - Follow the project's code style
   - Test your changes thoroughly

3. **Commit Your Changes**
   - Use clear, descriptive commit messages
   - Keep commits focused and atomic
   - Example format:
     ```bash
     git commit -m "feat: Add support for converting GameMaker sequences"
     ```

4. **Push to Your Fork**
   ```bash
   git push origin feature/your-feature-name
   ```

5. **Create a Pull Request**
   - Go to the [GM2Godot repository](https://github.com/Infiland/GM2Godot)
   - Click "New Pull Request"
   - Select your fork and branch
   - Fill out the PR template
   - Add screenshots for UI changes

## Testing

Before submitting a PR:
- Test your changes with both GameMaker and Godot projects
- Verify the UI works at different resolutions
- Check that existing features still work
- Test on different platforms if possible

## Areas for Contribution

We particularly welcome contributions in these areas:
- GML to GDScript conversion
- Additional asset type support
- UI/UX improvements
- Documentation improvements
- Bug fixes
- Performance optimizations

## Localization

To localize GM2Godot into other languages, create a copy of the Template.json file found in the Languages folder in GM2Godot's root directory. Rename the file to the chosen language's ISO-639 (Set 1) code (for example, en for English). Refer to https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes for a list of languages and their corresponding ISO-639 codes.
More information regarding localization can be found in the README section of the Template.json file.

## Questions or Issues?

- Check existing [issues](https://github.com/Infiland/GM2Godot/issues)
- Create a new issue for bugs or feature requests
- Join our community discussions (Add community links)

## Code of Conduct

- Be respectful and inclusive
- Help others learn and grow
- Focus on constructive feedback
- Follow the project's code of conduct (Add link if available)

## License

By contributing to GM2Godot, you agree that your contributions will be licensed under the same license as the project (Add license information).
