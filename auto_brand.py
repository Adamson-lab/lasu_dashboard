import os

def inject_global_branding():
    template_dir = 'templates'
    
    # The exact HTML payload we are injecting
    favicon_payload = '\n    \n    <link rel="icon" type="image/jpeg" href="{{ url_for(\'static\', filename=\'lasu_logo.jpg\') }}">\n'
    
    updated_count = 0
    skipped_count = 0
    
    print("Initiating Global Branding Sequence...")
    
    # Loop through every single file in the templates folder
    for filename in os.listdir(template_dir):
        if filename.endswith('.html'):
            filepath = os.path.join(template_dir, filename)
            
            with open(filepath, 'r', encoding='utf-8') as file:
                content = file.read()
            
            # Smart Sensor: Don't inject if it's already there, and ensure a </head> tag exists
            if 'lasu_logo.jpg' not in content and '</head>' in content:
                # Surgically inject the payload right above the closing head tag
                new_content = content.replace('</head>', f'{favicon_payload}</head>')
                
                with open(filepath, 'w', encoding='utf-8') as file:
                    file.write(new_content)
                    
                print(f"✅ Branded: {filename}")
                updated_count += 1
            else:
                skipped_count += 1
                
    print("--------------------------------------------------")
    print(f"🚀 MATRIX UPGRADE COMPLETE: {updated_count} files successfully branded. ({skipped_count} skipped/already branded).")

if __name__ == '__main__':
    inject_global_branding()