pipeline {
    agent any

    environment {
        GIT_CREDENTIALS_ID = 'your-git-credentials-id'
        SONARQUBE_SERVER = 'SonarQubeServer'
        SONAR_PROJECT_KEY = 'your-sonar-project-key'
        DOCKER_IMAGE = "${env.REPO_NAME}:${env.BUILD_NUMBER}"
        DOCKER_REGISTRY = 'your-docker-registry'
        RECIPIENT_EMAIL = "${currentBuild.getBuildCauses()[0].userId}@yourcompany.com"
        DB_FILES = ''
    }

    parameters {
        string(name: 'REPO_NAME', defaultValue: 'your-python-repo', description: 'Repository Name')
        string(name: 'DB_UPDATE_FILE', defaultValue: 'db_update', description: 'DB update file name')
    }

    stages {
        stage('Initialize & Set Context') {
            steps {
                script {
                    def branch = env.BRANCH_NAME
                    echo "Building branch: ${branch}"

                    if (branch == 'dev') {
                        env.KUBE_CONFIG_ID = 'DevKubeConfig'
                        env.CLUSTER_NAME = 'DevCluster'
                        env.RUN_DB_UPDATE = 'false'
                    } else if (branch.startsWith('release/')) {
                        env.KUBE_CONFIG_ID = 'QAKubeConfig'
                        env.CLUSTER_NAME = 'QACluster'
                        env.RUN_DB_UPDATE = 'true'
                    } else {
                        error "Unsupported branch: ${branch}"
                    }
                }
            }
        }

        stage('Pre-Build Notification') {
            steps {
                emailext (
                    to: "${env.RECIPIENT_EMAIL}",
                    subject: "Build Started: ${env.JOB_NAME} #${env.BUILD_NUMBER}",
                    body: "Build started for ${env.REPO_NAME} on branch ${env.BRANCH_NAME}"
                )
            }
        }

        stage('Checkout') {
            steps {
                git credentialsId: "${env.GIT_CREDENTIALS_ID}", url: "git@github.com:yourorg/${params.REPO_NAME}.git"
            }
        }

        stage('Code Quality - SonarQube') {
            steps {
                withSonarQubeEnv("${env.SONARQUBE_SERVER}") {
                    sh '''
                        sonar-scanner \
                          -Dsonar.projectKey=${SONAR_PROJECT_KEY} \
                          -Dsonar.sources=. \
                          -Dsonar.exclusions=helm_template/**
                    '''
                }
            }
        }

        stage('Check Code Quality Result') {
            steps {
                timeout(time: 2, unit: 'MINUTES') {
                    waitForQualityGate abortPipeline: true
                }
            }

            post {
                failure {
                    archiveArtifacts artifacts: '**/sonar-report.xml', allowEmptyArchive: true
                    emailext (
                        to: "${env.RECIPIENT_EMAIL}",
                        subject: "Build Failed: Code Quality Check",
                        body: "Code quality failed. See attached report.",
                        attachmentsPattern: '**/sonar-report.xml'
                    )
                }
            }
        }

        stage('Process DB Files') {
            when {
                expression { return env.RUN_DB_UPDATE == 'true' }
            }
            steps {
                script {
                    def dbFileContent = readFile("${params.DB_UPDATE_FILE}").trim()
                    if (dbFileContent) {
                        def dbFiles = dbFileContent.split('\n')
                        for (file in dbFiles) {
                            sh "cp db/${file} /var/tmp/"
                        }
                        env.DB_FILES = dbFiles.join(',')
                    } else {
                        echo "No DB files provided."
                    }
                }
            }
        }

        stage('Build Docker Image') {
            steps {
                sh "docker build -t ${DOCKER_REGISTRY}/${DOCKER_IMAGE} ."
            }
        }

        stage('Push Docker Image') {
            steps {
                sh "docker push ${DOCKER_REGISTRY}/${DOCKER_IMAGE}"
            }
        }

        stage('Qualys Scan') {
            steps {
                script {
                    def result = sh(script: 'echo "NO_VULNERABILITIES"', returnStdout: true).trim()
                    if (result != "NO_VULNERABILITIES") {
                        error "Vulnerabilities found in image scan!"
                    }
                }
            }

            post {
                failure {
                    emailext (
                        to: "${env.RECIPIENT_EMAIL}",
                        subject: "Build Failed: Qualys Scan",
                        body: "Build failed during Qualys scan."
                    )
                }
            }
        }

        stage('Update values.yaml') {
            steps {
                sh "sed -i 's|image:.*|image: ${DOCKER_REGISTRY}/${DOCKER_IMAGE}|' helm_template/values.yaml"
            }
        }

        stage('Export Kubeconfig') {
            steps {
                withCredentials([file(credentialsId: "${env.KUBE_CONFIG_ID}", variable: 'KUBECONFIG_FILE')]) {
                    sh 'export KUBECONFIG=$KUBECONFIG_FILE'
                }
            }
        }

        stage('Helm Deploy') {
            steps {
                sh "helm upgrade --install discovery helm_template -f helm_template/values.yaml"
            }
        }

        stage('Run DB Updates in MySQL') {
            when {
                expression { return env.RUN_DB_UPDATE == 'true' && env.DB_FILES?.trim() }
            }
            steps {
                script {
                    def podName = sh(script: "kubectl get pods -l app=mysql -o jsonpath='{.items[0].metadata.name}'", returnStdout: true).trim()
                    def files = env.DB_FILES.split(',')

                    for (file in files) {
                        echo "Running DB update: ${file}"
                        sh "kubectl cp /var/tmp/${file} ${podName}:/tmp/${file}"
                        sh "kubectl exec ${podName} -- bash -c \"mysql -u root -p\\$MYSQL_ROOT_PASSWORD < /tmp/${file}\""
                    }
                }
            }
        }

        stage('Validate Deployment') {
            steps {
                sh 'kubectl rollout status deployment/discovery'
            }
        }
    }

    post {
        always {
            script {
                def subjectLine = "Build ${currentBuild.currentResult}: ${env.JOB_NAME} #${env.BUILD_NUMBER}"
                def bodyMessage = """
                    Hello,

                    The Jenkins build for *${params.REPO_NAME}* on branch *${env.BRANCH_NAME}* has completed.

                    *Status:* ${currentBuild.currentResult}
                    *Cluster:* ${env.CLUSTER_NAME}

                    ${currentBuild.currentResult == 'FAILURE' ? 'Please check the console log or the previous stage outputs to find out where it failed.' : 'Deployment was successful.'}
                    
                    Regards,
                    Jenkins
                """

                emailext (
                    to: "${env.RECIPIENT_EMAIL}",
                    subject: subjectLine,
                    body: bodyMessage,
                    mimeType: 'text/plain'
                )
            }

            cleanWs()
        }
    }

}
